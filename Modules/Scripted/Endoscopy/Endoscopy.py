import ctk
import numpy as np
import qt
import slicer
import vtk
import vtk.util.numpy_support


class Endoscopy(slicer.ScriptedLoadableModule.ScriptedLoadableModule):
    """Uses slicer.ScriptedLoadableModule.ScriptedLoadableModule base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def __init__(self, parent):
        slicer.ScriptedLoadableModule.ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = "Endoscopy"
        self.parent.categories = ["Endoscopy"]
        self.parent.dependencies = []
        self.parent.contributors = ["Steve Pieper (Isomics)", "Harald Scheirich (Kitware)", "Lee Newberg (Kitware)"]
        self.parent.helpText = """
Create a path model as a spline interpolation of a set of fiducial points.
Pick the Camera to be modified by the path and the Fiducial List defining the control points.
Clicking "Create path" will make a path model and enable the flythrough panel.
You can manually scroll through the path with the Frame slider. The Play/Pause button toggles animated flythrough.
The Frame Skip slider speeds up the animation by skipping points on the path.
The Frame Delay slider slows down the animation by adding more time between frames.
The View Angle provides is used to approximate the optics of an endoscopy system.
"""
        self.parent.helpText += self.getDefaultModuleDocumentationLink()
        self.parent.acknowledgementText = """
This work is supported by PAR-07-249: R01CA131718 NA-MIC Virtual Colonoscopy
(See <a>https://www.na-mic.org/Wiki/index.php/NA-MIC_NCBC_Collaboration:NA-MIC_virtual_colonoscopy</a>)
NA-MIC, NAC, BIRN, NCIGT, and the Slicer Community.
"""


class EndoscopyWidget(slicer.ScriptedLoadableModule.ScriptedLoadableModuleWidget):
    """Uses slicer.ScriptedLoadableModule.ScriptedLoadableModuleWidget base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """

    # TODO: Need to use logic of https://github.com/Slicer/Slicer/pull/6541/files, Lines 465 and following to handle
    # user's use of the new GUI.

    def __init__(self, parent=None):
        slicer.ScriptedLoadableModule.ScriptedLoadableModuleWidget.__init__(self, parent)
        self.transform = None
        self.inputCurve = None
        self.resampledCurve = None
        self.skip = 0
        self.logic = None
        self.timer = qt.QTimer()
        print('        self.timer = qt.QTimer()')
        self.timer.setInterval(20)
        self.timer.connect('timeout()', self.flyToNext)
        print('            self.timer.connect("timeout()", self.flyToNext)')

        self.cameraNodeObserverTags = []
        self.cameraNode = None
        self.cameraObserverTags = []
        self.camera = None
        self.cursorNodeObserverTags = []
        self.cursorNode = None
        self.fiducialNodeObserverTags = []
        self.fiducialNode = None

    def setup(self):
        """
        This builds:
                self.timer = qt.QTimer()
                    self.timer.connect("timeout()", self.flyToNext)
            pathCollapsibleButton = ctk.ctkCollapsibleButton()
                self.layout.addWidget(pathCollapsibleButton)
                pathFormLayout = qt.QFormLayout(pathCollapsibleButton)
                cameraNodeSelector = slicer.qMRMLNodeComboBox()
                    cameraNodeSelector.connect("currentNodeChanged(bool)", self.enableOrDisableCreateButton)
                    cameraNodeSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.setCameraNode)
                    pathFormLayout.addRow("Camera:", cameraNodeSelector)
                inputFiducialNodeSelector = slicer.qMRMLNodeComboBox()
                    inputFiducialNodeSelector.connect("currentNodeChanged(bool)", self.enableOrDisableCreateButton)
                    inputFiducialNodeSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.setFiducialNode)
                    pathFormLayout.addRow("Input Fiducial Nodes:", inputFiducialNodeSelector)
                outputPathNodeSelector = slicer.qMRMLNodeComboBox()
                    outputPathNodeSelector.connect("currentNodeChanged(bool)", self.enableOrDisableCreateButton)
                    pathFormLayout.addRow("Output Path:", outputPathNodeSelector)
                createPathButton = qt.QPushButton("Create path")
                    createPathButton.connect("clicked()", self.onCreatePathButtonClicked)
                    pathFormLayout.addRow(createPathButton)
            keyframeCollapsibleButton = ctk.ctkCollapsibleButton()
                self.layout.addWidget(keyframeCollapsibleButton)
                keyframeLayout = qt.QFormLayout(keyframeCollapsibleButton)
                keyframeSlider = ctk.ctkSliderWidget()
                    keyframeSlider.connect("valueChanged(double)", self.selectControlPoint)
                    keyframeLayout.addRow("Frame:", keyframeSlider)
                refreshButton = qt.QPushButton("Refresh Rotations")
                    refreshButton.connect("clicked()", self.refreshOrientations)
                    keyframeLayout.addRow(refreshButton)
            flythroughCollapsibleButton = ctk.ctkCollapsibleButton()
                self.layout.addWidget(flythroughCollapsibleButton)
                flythroughFormLayout = qt.QFormLayout(flythroughCollapsibleButton)
                frameSlider = ctk.ctkSliderWidget()
                    frameSlider.connect("valueChanged(double)", self.frameSliderValueChanged)
                    flythroughFormLayout.addRow("Frame:", frameSlider)
                frameSkipSlider = ctk.ctkSliderWidget()
                    frameSkipSlider.connect("valueChanged(double)", self.frameSkipSliderValueChanged)
                    flythroughFormLayout.addRow("Frame skip:", frameSkipSlider)
                frameDelaySlider = ctk.ctkSliderWidget()
                    frameDelaySlider.connect("valueChanged(double)", self.frameDelaySliderValueChanged)
                    flythroughFormLayout.addRow("Frame delay:", frameDelaySlider)
                viewAngleSlider = ctk.ctkSliderWidget()
                    viewAngleSlider.connect("valueChanged(double)", self.viewAngleSliderValueChanged)
                    flythroughFormLayout.addRow("View Angle:", viewAngleSlider)
                playButton = qt.QPushButton("Play")
                    playButton.connect("toggled(bool)", self.onPlayButtonToggled)
                    flythroughFormLayout.addRow(playButton)
            self.layout.addStretch(1)
            self.cameraNodeObserverTags = [newCameraNode.AddObserver(vtk.vtkCommand.ModifiedEvent, self.onCameraNodeModified)]
            self.cameraObserverTags = [newCamera.AddObserver(vtk.vtkCommand.ModifiedEvent, self.onCameraNodeModified)]
            self.cursorNodeObserverTags = [self.cursorNode.AddObserver(vtk.vtkCommand.ModifiedEvent, self.cursorModified)]
            self.fiducialNodeObserverTags = [newFiducialNode.AddObserver(vtk.vtkCommand.ModifiedEvent, self.onFiducialNodeModified)]
        """

        slicer.ScriptedLoadableModule.ScriptedLoadableModuleWidget.setup(self)
        self.setupPathUI()
        self.setupKeyframeUI()
        self.setupFlythroughUI()

        # Add vertical spacer
        self.layout.addStretch(1)
        print('self.layout.addStretch(1)')

        self.cameraNodeSelector.setMRMLScene(slicer.mrmlScene)
        self.inputFiducialNodeSelector.setMRMLScene(slicer.mrmlScene)
        self.outputPathNodeSelector.setMRMLScene(slicer.mrmlScene)

    def setupPathUI(self):
        # Path collapsible button
        pathCollapsibleButton = ctk.ctkCollapsibleButton()
        print('pathCollapsibleButton = ctk.ctkCollapsibleButton()')
        pathCollapsibleButton.text = "Path"
        self.layout.addWidget(pathCollapsibleButton)
        print('    self.layout.addWidget(pathCollapsibleButton)')

        # Layout within the path collapsible button
        pathFormLayout = qt.QFormLayout(pathCollapsibleButton)
        print('    pathFormLayout = qt.QFormLayout(pathCollapsibleButton)')

        # Camera node selector
        cameraNodeSelector = slicer.qMRMLNodeComboBox()
        print('    cameraNodeSelector = slicer.qMRMLNodeComboBox()')
        cameraNodeSelector.objectName = 'cameraNodeSelector'
        cameraNodeSelector.toolTip = "Select a camera that will fly along this path."
        cameraNodeSelector.nodeTypes = ['vtkMRMLCameraNode']
        cameraNodeSelector.noneEnabled = False
        cameraNodeSelector.addEnabled = False
        cameraNodeSelector.removeEnabled = False
        cameraNodeSelector.connect('currentNodeChanged(bool)', self.enableOrDisableCreateButton)
        print('        cameraNodeSelector.connect("currentNodeChanged(bool)", self.enableOrDisableCreateButton)')
        cameraNodeSelector.connect('currentNodeChanged(vtkMRMLNode*)', self.setCameraNode)
        print('        cameraNodeSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.setCameraNode)')
        pathFormLayout.addRow("Camera:", cameraNodeSelector)
        print('        pathFormLayout.addRow("Camera:", cameraNodeSelector)')
        self.cameraNodeSelector = cameraNodeSelector

        # Input fiducial node selector
        inputFiducialNodeSelector = slicer.qMRMLNodeComboBox()
        print('    inputFiducialNodeSelector = slicer.qMRMLNodeComboBox()')
        inputFiducialNodeSelector.objectName = 'inputFiducialNodeSelector'
        inputFiducialNodeSelector.toolTip = "Select a fiducial list to define control points for the path."
        inputFiducialNodeSelector.nodeTypes = ['vtkMRMLMarkupsFiducialNode', 'vtkMRMLMarkupsCurveNode']
        inputFiducialNodeSelector.noneEnabled = False
        inputFiducialNodeSelector.addEnabled = False
        inputFiducialNodeSelector.removeEnabled = False
        inputFiducialNodeSelector.connect('currentNodeChanged(bool)', self.enableOrDisableCreateButton)
        print('        inputFiducialNodeSelector.connect("currentNodeChanged(bool)", self.enableOrDisableCreateButton)')
        inputFiducialNodeSelector.connect('currentNodeChanged(vtkMRMLNode*)', self.setFiducialNode)
        print('        inputFiducialNodeSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.setFiducialNode)')
        pathFormLayout.addRow("Input Fiducial Nodes:", inputFiducialNodeSelector)
        print('        pathFormLayout.addRow("Input Fiducial Nodes:", inputFiducialNodeSelector)')
        self.inputFiducialNodeSelector = inputFiducialNodeSelector

        # Output path node selector
        outputPathNodeSelector = slicer.qMRMLNodeComboBox()
        print('    outputPathNodeSelector = slicer.qMRMLNodeComboBox()')
        outputPathNodeSelector.objectName = 'outputPathNodeSelector'
        outputPathNodeSelector.toolTip = "Select a fiducial list to define control points for the path."
        outputPathNodeSelector.nodeTypes = ['vtkMRMLModelNode']
        outputPathNodeSelector.noneEnabled = False
        outputPathNodeSelector.addEnabled = True
        outputPathNodeSelector.removeEnabled = True
        outputPathNodeSelector.renameEnabled = True
        outputPathNodeSelector.connect('currentNodeChanged(bool)', self.enableOrDisableCreateButton)
        print('        outputPathNodeSelector.connect("currentNodeChanged(bool)", self.enableOrDisableCreateButton)')
        pathFormLayout.addRow("Output Path:", outputPathNodeSelector)
        print('        pathFormLayout.addRow("Output Path:", outputPathNodeSelector)')
        self.outputPathNodeSelector = outputPathNodeSelector

        # CreatePath button
        createPathButton = qt.QPushButton("Create path")
        print('    createPathButton = qt.QPushButton("Create path")')
        createPathButton.toolTip = "Create the path."
        createPathButton.enabled = False
        createPathButton.connect('clicked()', self.onCreatePathButtonClicked)
        print('        createPathButton.connect("clicked()", self.onCreatePathButtonClicked)')
        pathFormLayout.addRow(createPathButton)
        print('        pathFormLayout.addRow(createPathButton)')
        self.createPathButton = createPathButton

    def setupKeyframeUI(self):
        keyframeCollapsibleButton = ctk.ctkCollapsibleButton()
        print('keyframeCollapsibleButton = ctk.ctkCollapsibleButton()')
        keyframeCollapsibleButton.text = "Keyframes"
        keyframeCollapsibleButton.enabled = False
        self.layout.addWidget(keyframeCollapsibleButton)
        print('    self.layout.addWidget(keyframeCollapsibleButton)')
        self.keyframeCollapsibleButton = keyframeCollapsibleButton

        keyframeLayout = qt.QFormLayout(keyframeCollapsibleButton)
        print('    keyframeLayout = qt.QFormLayout(keyframeCollapsibleButton)')

        # KeyFrame slider
        keyframeSlider = ctk.ctkSliderWidget()
        print('    keyframeSlider = ctk.ctkSliderWidget()')
        keyframeSlider.decimals = 0
        keyframeSlider.minimum = 0
        keyframeSlider.connect('valueChanged(double)', self.selectControlPoint)
        print('        keyframeSlider.connect("valueChanged(double)", self.selectControlPoint)')
        keyframeLayout.addRow("Frame:", keyframeSlider)
        print('        keyframeLayout.addRow("Frame:", keyframeSlider)')
        self.keyframeSlider = keyframeSlider

        refreshButton = qt.QPushButton("Refresh Rotations")
        print('    refreshButton = qt.QPushButton("Refresh Rotations")')
        refreshButton.connect('clicked()', self.refreshOrientations)
        print('        refreshButton.connect("clicked()", self.refreshOrientations)')
        keyframeLayout.addRow(refreshButton)
        print('        keyframeLayout.addRow(refreshButton)')

    def setupFlythroughUI(self):
        # Flythrough collapsible button
        flythroughCollapsibleButton = ctk.ctkCollapsibleButton()
        print('flythroughCollapsibleButton = ctk.ctkCollapsibleButton()')
        flythroughCollapsibleButton.text = "Flythrough"
        flythroughCollapsibleButton.enabled = False
        self.layout.addWidget(flythroughCollapsibleButton)
        print('    self.layout.addWidget(flythroughCollapsibleButton)')
        self.flythroughCollapsibleButton = flythroughCollapsibleButton

        # Layout within the Flythrough collapsible button
        flythroughFormLayout = qt.QFormLayout(flythroughCollapsibleButton)
        print('    flythroughFormLayout = qt.QFormLayout(flythroughCollapsibleButton)')

        # Frame slider
        frameSlider = ctk.ctkSliderWidget()
        print('    frameSlider = ctk.ctkSliderWidget()')
        frameSlider.decimals = 0
        frameSlider.connect('valueChanged(double)', self.frameSliderValueChanged)
        print('        frameSlider.connect("valueChanged(double)", self.frameSliderValueChanged)')
        flythroughFormLayout.addRow("Frame:", frameSlider)
        print('        flythroughFormLayout.addRow("Frame:", frameSlider)')
        self.frameSlider = frameSlider

        # Frame skip slider
        frameSkipSlider = ctk.ctkSliderWidget()
        print('    frameSkipSlider = ctk.ctkSliderWidget()')
        frameSkipSlider.decimals = 0
        frameSkipSlider.minimum = 0
        frameSkipSlider.maximum = 50
        frameSkipSlider.connect('valueChanged(double)', self.frameSkipSliderValueChanged)
        print('        frameSkipSlider.connect("valueChanged(double)", self.frameSkipSliderValueChanged)')
        flythroughFormLayout.addRow("Frame skip:", frameSkipSlider)
        print('        flythroughFormLayout.addRow("Frame skip:", frameSkipSlider)')

        # Frame delay slider
        frameDelaySlider = ctk.ctkSliderWidget()
        print('    frameDelaySlider = ctk.ctkSliderWidget()')
        frameDelaySlider.decimals = 0
        frameDelaySlider.minimum = 5
        frameDelaySlider.maximum = 100
        frameDelaySlider.suffix = " ms"
        frameDelaySlider.value = 20
        frameDelaySlider.connect('valueChanged(double)', self.frameDelaySliderValueChanged)
        print('        frameDelaySlider.connect("valueChanged(double)", self.frameDelaySliderValueChanged)')
        flythroughFormLayout.addRow("Frame delay:", frameDelaySlider)
        print('        flythroughFormLayout.addRow("Frame delay:", frameDelaySlider)')

        # View angle slider
        viewAngleSlider = ctk.ctkSliderWidget()
        print('    viewAngleSlider = ctk.ctkSliderWidget()')
        viewAngleSlider.decimals = 0
        viewAngleSlider.minimum = 30
        viewAngleSlider.maximum = 180
        viewAngleSlider.connect('valueChanged(double)', self.viewAngleSliderValueChanged)
        print('        viewAngleSlider.connect("valueChanged(double)", self.viewAngleSliderValueChanged)')
        flythroughFormLayout.addRow("View Angle:", viewAngleSlider)
        print('        flythroughFormLayout.addRow("View Angle:", viewAngleSlider)')
        self.viewAngleSlider = viewAngleSlider

        # Play button
        playButton = qt.QPushButton("Play")
        print('    playButton = qt.QPushButton("Play")')
        playButton.toolTip = "Fly through path."
        playButton.checkable = True
        playButton.connect('toggled(bool)', self.onPlayButtonToggled)
        print('        playButton.connect("toggled(bool)", self.onPlayButtonToggled)')
        flythroughFormLayout.addRow(playButton)
        print('        flythroughFormLayout.addRow(playButton)')
        self.playButton = playButton

    def setupCursor(self):
        self.cursorNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsPlaneNode", "EndoscopyCursor")
        print('    self.cursorNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsPlaneNode", "EndoscopyCursor")')
        self.cursorNode.AddControlPoint(0, 0, 0)
        # planeMarkupDisplayNode.SetGlyphSize(0.0001)
        # hack to hide sphere glyph that can also be used for translating by
        # grabbing with mouse.  We don't want the user to directly translate
        # these planes. planeMarkupDisplayNode.SetGlyphScale(0.0001) hack to
        # hide sphere glyph that can also be used for translating by
        # grabbing with mouse. We don't want the user to directly translate
        # these planes.
        self.cursorNode.SetNthControlPointVisibility(0, False)
        self.cursorNode.SetNthControlPointVisibility(1, False)
        self.cursorNode.SetSize(20.0, 20.0)
        display = self.cursorNode.GetMarkupsDisplayNode()
        display.SetTranslationHandleVisibility(False)
        display.SetScaleHandleVisibility(False)
        display.SetRotationHandleVisibility(True)
        display.SetPropertiesLabelVisibility(False)

        self.cursorNodeObserverTags.append(
            self.cursorNode.AddObserver(vtk.vtkCommand.ModifiedEvent, self.cursorModified)
        )
        print(
            'self.cursorNodeObserverTags.append(self.cursorNode.AddObserver(vtk.vtkCommand.ModifiedEvent, self.cursorModified))'
        )
        print('Where is cursorNode in the scene?')

    def cleanup(self):
        if self.logic:
            self.logic.cleanup()
        self.logic = None
        for tags, node in [
            (self.cameraNodeObserverTags, self.cameraNode),
            (self.cameraObserverTags, self.camera),
            (self.cursorNodeObserverTags, self.cursorNode),
            (self.fiducialNodeObserverTags, self.fiducialNode),
        ]:
            if node:
                for tag in tags:
                    node.RemoveObserver(tag)

        for node in [self.cursorNode, self.transform]:
            # TODO: Is this right?
            if node:
                slicer.mrmlScene.RemoveNode(node)

        self.cameraNodeObserverTags = []
        self.cameraNode = None
        self.cameraObserverTags = []
        self.camera = None
        self.cursorNodeObserverTags = []
        self.cursorNode = None
        self.fiducialNodeObserverTags = []
        self.fiducialNode = None

        slicer.ScriptedLoadableModule.ScriptedLoadableModuleWidget.cleanup(self)

    def setCameraNode(self, newCameraNode):
        """Allow to set the current camera node.
        Connected to signal 'currentNodeChanged()' emitted by camera node selector."""

        #  Remove previous observers
        if self.cameraNode:
            for tag in self.cameraNodeObserverTags:
                self.cameraNode.RemoveObserver(tags)
            self.cameraNodeObserverTags = []
        if self.camera:
            for tag in self.cameraObserverTags:
                self.camera.RemoveObserver(tag)
            self.cameraObserverTags = []

        newCamera = None
        if newCameraNode:
            newCamera = newCameraNode.GetCamera()
            # Add CameraNode ModifiedEvent observer
            self.cameraNodeObserverTags.append(
                newCameraNode.AddObserver(vtk.vtkCommand.ModifiedEvent, self.onCameraNodeModified)
            )
            print(
                'self.cameraNodeObserverTags.append(newCameraNode.AddObserver(vtk.vtkCommand.ModifiedEvent, self.onCameraNodeModified))'
            )
            # Add Camera ModifiedEvent observer
            self.cameraObserverTags.append(
                newCamera.AddObserver(vtk.vtkCommand.ModifiedEvent, self.onCameraNodeModified)
            )
            print(
                'self.cameraObserverTags.append(newCamera.AddObserver(vtk.vtkCommand.ModifiedEvent, self.onCameraNodeModified))'
            )

        self.cameraNode = newCameraNode
        self.camera = newCamera

        # Update UI
        self.updateWidgetFromMRML()

    def setFiducialNode(self, newFiducialNode):
        """Allow to set the current list of input nodes.
        Connected to signal 'currentNodeChanged()' emitted by fiducial node selector."""
        #  Remove previous observer
        if self.fiducialNode:
            for tag in self.fiducialNodeObserverTags:
                self.fiducialNode.RemoveObserver(tag)
            self.fiducialNodeObserverTags = []

        if newFiducialNode:
            # Add CameraNode ModifiedEvent observer
            self.fiducialNodeObserverTags.append(
                newFiducialNode.AddObserver(vtk.vtkCommand.ModifiedEvent, self.onFiducialNodeModified)
            )
            print(
                'self.fiducialNodeObserverTags.append(newFiducialNode.AddObserver(vtk.vtkCommand.ModifiedEvent, self.onFiducialNodeModified))'
            )
            self.logic = EndoscopyLogic(newFiducialNode)
            self.keyframeCollapsibleButton.enabled = True
            # TODO: Maybe.  Remove old observers from pre-existing self.curveNode.
            # TODO: Maybe.  Copy newFiducialNode to self.curveNode.
            # TODO: Maybe.  Then AddObserver???
            # self.curveNodeObserverTags.extend(
            #     [
            #         self.curveNode.AddObserver(vtk.vtkCommand.ModifiedEvent, self.controlPointsModified),
            #         self.curveNode.AddObserver(slicer.vtkMRMLMarkupsNode.PointModifiedEvent, self.controlPointModified),
            #     ]
            # )

            # keyframeSlider selects a control point (not a segment) so index goes up to n - 1
            self.keyframeSlider.maximum = newFiducialNode.GetNumberOfControlPoints() - 1
        else:
            self.keyframeCollapsibleButton.enabled = False
            self.keyframeSlider.maximum = 0

        self.fiducialNode = newFiducialNode

        # Update UI
        self.updateWidgetFromMRML()

    def updateWidgetFromMRML(self):
        if self.camera:
            self.viewAngleSlider.value = self.camera.GetViewAngle()
        if self.cameraNode:
            pass
        if self.fiducialNode:
            # TODO: We should correctly read the number of points and update the keyframes
            pass

    def onCameraModified(self, observer, eventid):
        self.updateWidgetFromMRML()

    def onCameraNodeModified(self, observer, eventid):
        self.updateWidgetFromMRML()

    def enableOrDisableCreateButton(self):
        """Connected to both the fiducial and camera node selector. It allows to
        enable or disable the 'create path' button."""
        self.createPathButton.enabled = (
            self.cameraNodeSelector.currentNode()
            and self.inputFiducialNodeSelector.currentNode()
            and self.outputPathNodeSelector.currentNode()
        )

    def onFiducialNodeModified(self, observer, eventid):
        """If the fiducial was changed we need to repopulate the keyframe UI"""
        # Hack rebuild path just to get the new data
        if self.fiducialNode:
            self.logic = EndoscopyLogic(self.fiducialNode)
            # keyframeSlider selects a control point (not a segment) so index goes up to self.logic.n - 1
            self.keyframeSlider.maximum = self.logic.n - 1

    def onCreatePathButtonClicked(self):
        """Connected to 'create path' button. It allows to:
        - compute the path
        - create the associated model"""

        fiducialNode = self.inputFiducialNodeSelector.currentNode()
        outputPathNode = self.outputPathNodeSelector.currentNode()
        print("Calculating Path...")
        self.logic = EndoscopyLogic(fiducialNode)
        numberOfControlPoints = self.logic.resampledCurve.GetNumberOfControlPoints()
        print("-> Computed path contains %d elements" % numberOfControlPoints)

        print("Create Model...")
        model = EndoscopyPathModel(self.logic.resampledCurve, fiducialNode, outputPathNode)
        print("-> Model created")

        # Update frame slider range
        self.frameSlider.maximum = max(0, numberOfControlPoints - 2)

        # Update flythrough variables
        self.camera = self.camera
        self.transform = model.transform
        self.planeNormal = self.logic.planeNormal
        self.resampledCurve = self.logic.resampledCurve

        # Enable / Disable flythrough button
        self.flythroughCollapsibleButton.enabled = numberOfControlPoints > 1

    def frameSliderValueChanged(self, newValue):
        self.flyTo(int(newValue))

    def frameSkipSliderValueChanged(self, newValue):
        self.skip = int(newValue)

    def frameDelaySliderValueChanged(self, newValue):
        self.timer.interval = newValue

    def viewAngleSliderValueChanged(self, newValue):
        if self.cameraNode:
            self.cameraNode.GetCamera().SetViewAngle(newValue)

    def onPlayButtonToggled(self, checked):
        if checked:
            self.timer.start()
            self.playButton.text = "Stop"
        else:
            self.timer.stop()
            self.playButton.text = "Play"

    def selectControlPoints(self, mrmlNode):
        # TODO: Write me
        print("selectControlPoints called")

    def refreshOrientations(self):
        # TODO: Write me
        print("refreshOrientations called")

    def selectControlPoint(self, index):
        # TODO: Write me
        self.keyframeSlider
        print(f"selectControlPoint called for Frame {int(self.keyframeSlider.value)}")

    def controlPointsModified(self, observer, eventid):
        # TODO: Write me
        print("controlPointsModified called")

    def controlPointModified(self, observer, eventid):
        # TODO: Write me
        print("controlPointModified called")

    def cursorModified(self, observer, eventid):
        # TODO: Write me
        print("cursorModified called")

    def flyToNext(self):
        currentStep = self.frameSlider.value
        nextStep = currentStep + self.skip + 1
        if nextStep >= self.logic.resampledCurve.GetNumberOfControlPoints() - 1:
            nextStep = 0
        self.frameSlider.value = nextStep

    def flyTo(self, pathPointIndex):
        if self.resampledCurve is None:
            return

        pathPointIndex = int(pathPointIndex)
        cameraPosition = np.zeros((3,))
        print(f"flyTo {pathPointIndex} of {self.resampledCurve.GetNumberOfControlPoints()}")
        self.resampledCurve.GetNthControlPointPositionWorld(pathPointIndex, cameraPosition)
        focalPointPosition = np.zeros((3,))
        self.resampledCurve.GetNthControlPointPositionWorld(pathPointIndex + 1, focalPointPosition)

        defaultOrientation = self.logic.getDefaultOrientation(self.resampledCurve, pathPointIndex)
        relativeOrientation = np.zeros((4,))
        self.resampledCurve.GetNthControlPointOrientation(pathPointIndex, relativeOrientation)
        resultMatrix = np.matmul(
            EndoscopyLogic.OrientationToMatrix3x3(relativeOrientation),
            EndoscopyLogic.OrientationToMatrix3x3(defaultOrientation),
        )

        # Build a 4x4 matrix from the 3x3 matrix and the camera position
        toParent = vtk.vtkMatrix4x4()
        for j in range(3):
            for i in range(3):
                toParent.SetElement(i, j, resultMatrix[i, j])
            toParent.SetElement(3, j, 0.0)

        toParent.SetElement(0, 3, cameraPosition[0])
        toParent.SetElement(1, 3, cameraPosition[1])
        toParent.SetElement(2, 3, cameraPosition[2])
        toParent.SetElement(3, 3, 1.0)

        # Work on camera and cameraNode
        wasModified = self.cameraNode.StartModify()
        self.camera.SetPosition(*cameraPosition)
        self.camera.SetFocalPoint(*focalPointPosition)
        self.camera.OrthogonalizeViewUp()
        self.transform.SetMatrixTransformToParent(toParent)
        self.cameraNode.EndModify(wasModified)
        self.cameraNode.ResetClippingRange()


class EndoscopyLogic:
    """Compute path given a list of fiducial nodes.
    Path is stored in 'path' member variable as a numpy array.
    If a point list is received then curve points are generated using Hermite spline interpolation.
    See https://en.wikipedia.org/wiki/Cubic_Hermite_spline

    Example:
      self.logic = EndoscopyLogic(inputMarkupsFiducialNode)
      print("computer path has %d elements" % self.logic.resampledCurve.GetNumberOfControlPoints())

    Note:
    * `orientation` = (angle, *axis), where angle is in radians and axis is the unit 3D-vector for the axis of rotation.
    * `quaternion` = (cos(angle/2), *axis * sin(angle/2))
    * `matrix` = matrix with columns x, y, and z, which are unit vectors for the rotated frame
    """

    def __init__(self, inputMarkupsFiducialNode, dl=0.5):
        self.dl = dl  # desired world space step size (in mm)
        self.setControlPoints(inputMarkupsFiducialNode)

    def __del__(self):
        self.cleanup()

    def cleanup(self):
        pass

    def setControlPoints(self, inputMarkupsFiducialNode):
        if not (
            self.setCurveFromFiducialInput(inputMarkupsFiducialNode)
            and self.setCameraPositionsFromInputCurve()
            and self.setCameraOrientationsFromInputCurve()
        ):
            self.indicateFailure()

    def setCurveFromFiducialInput(self, inputMarkupsFiducialNode):
        # Make a deep copy of the input information as a vtkMRMLMarkupsCurveNode.
        if (
            inputMarkupsFiducialNode.GetClassName() == "vtkMRMLMarkupsFiducialNode"
            or inputMarkupsFiducialNode.GetClassName() == "vtkMRMLMarkupsCurveNode"
        ):
            self.inputCurve = slicer.vtkMRMLMarkupsCurveNode()
        elif inputMarkupsFiducialNode.GetClassName() == "vtkMRMLMarkupsClosedCurveNode":
            self.inputCurve = slicer.vtkMRMLMarkupsClosedCurveNode()
        else:
            # Unrecognized type for inputMarkupsFiducialNode
            slicer.util.errorDisplay(
                "The inputMarkupsFiducialNode must be a vtkMRMLMarkupsFiducialNode, vtkMRMLMarkupsCurveNode, or"
                + " vtkMRMLMarkupsClosedCurveNode.  {inputMarkupsFiducialNode.GetClassName()} cannot be processed.",
                "Run Error",
            )
            return False

        # We have an input.  Check that it is big enough.
        n = inputMarkupsFiducialNode.GetNumberOfControlPoints()
        if n < 2:
            # Need at least two points to make segments.
            slicer.util.errorDisplay("You need at least 2 control points in order to make a fly through.", "Run Error")
            return False

        # Copy everything from the input
        self.inputCurve.Copy(inputMarkupsFiducialNode)
        return True

    def setCameraPositionsFromInputCurve(self):
        # We now have the user's input as a curve.  Let's get equidistant points to represent the curve.
        resampledPoints = vtk.vtkPoints()
        slicer.vtkMRMLMarkupsCurveNode.ResamplePoints(
            self.inputCurve.GetCurvePointsWorld(), resampledPoints, self.dl, self.inputCurve.GetCurveClosed()
        )
        self.n = resampledPoints.GetNumberOfPoints()
        if self.n < 2:
            curveLength = self.inputCurve.GetCurveLengthWorld()
            slicer.util.errorDisplay(
                "The curve length {curveLength} is too short to support a step size of {self.dl}.",
                "Run Error",
            )
            return False

        # Make a curve from these resampledPoints
        self.resampledCurve = slicer.vtkMRMLMarkupsCurveNode()
        wasModified = self.resampledCurve.StartModify()
        self.resampledCurve.Copy(self.inputCurve)
        self.resampledCurve.RemoveAllControlPoints()
        points = np.zeros((self.n, 3))
        for i in range(self.n):
            resampledPoints.GetPoint(i, points[i])
            self.resampledCurve.AddControlPointWorld(*points[i])
        self.resampledCurve.EndModify(wasModified)

        self.planePosition, self.planeNormal = EndoscopyLogic.PlaneFit(points.T)

        return True

    def setCameraOrientationsFromInputCurve(self):
        # Interpolate the camera orientations for our resampledPoints

        # Find the camera orientations in the input curve
        n = self.inputCurve.GetNumberOfControlPoints()
        quaternionInterpolator = vtk.vtkQuaternionInterpolator()
        quaternionInterpolator.SetSearchMethod(0)  # binary search
        quaternionInterpolator.SetInterpolationTypeToSpline()  # cubic rather than linear interpolation
        # If the curve is closed, put the first orientation also at the end
        lastN = n if self.inputCurve.GetClassName() == "vtkMRMLMarkupsClosedCurveNode" else n - 1
        for i in range(n):
            # TODO: For the moment assume that all orientations have been supplied by the user.  This loop should
            # instead include only user-supplied interpolations.  Those that are not supplied by the user, and thus are
            # in need of being computed via interpolation, should not be supplied via .AddQuaternion().
            supplied = True
            if supplied or i == 0 or i == lastN:
                distanceAlongInputCurve = EndoscopyLogic.distanceAlongCurveOfNthControlPointPositionWorld(
                    self.inputCurve, i
                )
                orientation = np.array([0.0, 0.0, 0.0, 1.0])
                if supplied:
                    self.getRelativeOrientation(self.inputCurve, i, orientation)
                quaternion = EndoscopyLogic.OrientationToQuaternion(orientation)
                if i == 0:
                    saveQuaternion = quaternion
                quaternionInterpolator.AddQuaternion(distanceAlongInputCurve, quaternion)
        if lastN == n:
            # For a closed curve, we put the first orientation at the end too
            distanceAlongInputCurve = self.inputCurve.GetCurveLengthWorld()
            quaternionInterpolator.AddQuaternion(distanceAlongInputCurve, saveQuaternion)

        # Find the places at which we wish to have orientations
        wasModified = self.resampledCurve.StartModify()
        # The curves have different resolutions so their lengths won't come out exactly the same.  We scale the
        # distances along self.resampledCurve with a fudgeFactor so that the lengths do come out the same.
        fudgeFactor = self.inputCurve.GetCurveLengthWorld() / self.resampledCurve.GetCurveLengthWorld()
        for i in range(self.n):
            distanceAlongInputCurve = (
                EndoscopyLogic.distanceAlongCurveOfNthControlPointPositionWorld(self.resampledCurve, i) * fudgeFactor
            )
            quaternion = np.zeros((4,))
            quaternionInterpolator.InterpolateQuaternion(distanceAlongInputCurve, quaternion)
            orientation = EndoscopyLogic.QuaternionToOrientation(quaternion)
            self.resampledCurve.SetNthControlPointOrientation(i, *orientation)
        self.resampledCurve.EndModify(wasModified)
        return True

    def getDefaultOrientation(self, curve, pathIndex, orientation=np.zeros((4,))):
        n = curve.GetNumberOfControlPoints()
        # If the curve is not closed then the last control point has the same orientation as its previous control point
        if pathIndex == n - 1 and curve.GetClassName() != "vtkMRMLMarkupsClosedCurveNode":
            pathIndex -= 1
        nextPathIndex = (pathIndex + 1) % n
        cameraPosition = np.zeros((3,))
        curve.GetNthControlPointPositionWorld(pathIndex, cameraPosition)
        # print(f"{cameraPosition = }")
        focalPointPosition = np.zeros((3,))
        curve.GetNthControlPointPositionWorld(nextPathIndex, focalPointPosition)
        # print(f"{focalPointPosition = }")
        matrix3x3 = np.zeros((3, 3))
        # camera forward
        matrix3x3[:, 2] = focalPointPosition - cameraPosition
        matrix3x3[:, 2] /= np.linalg.norm(matrix3x3[:, 2])
        # camera left
        matrix3x3[:, 0] = np.cross(self.planeNormal, matrix3x3[:, 2])
        matrix3x3[:, 0] /= np.linalg.norm(matrix3x3[:, 0])
        # camera up
        matrix3x3[:, 1] = np.cross(matrix3x3[:, 2], matrix3x3[:, 0])
        EndoscopyLogic.Matrix3x3ToOrientation(matrix3x3, orientation)
        print(f"getDefaultOrientation[{pathIndex}] ={orientation}")
        return orientation

    def getRelativeOrientation(self, curve, i, resultOrientation=np.zeros((4,))):
        rightOrientation = self.getDefaultOrientation(curve, i)
        # Compute the inverse of rightOrientation by negating its angle of rotation.
        rightOrientation[0] *= -1.0

        leftOrientation = np.zeros((4,))
        curve.GetNthControlPointOrientation(i, leftOrientation)

        return EndoscopyLogic.MultiplyOrientations(leftOrientation, rightOrientation, resultOrientation)

    def indicateFailure(self):
        # We need to stop the user from doing a fly through.  We will delete the required self.resampledCurve.
        self.resampledCurve = None

    @staticmethod
    def distanceAlongCurveOfNthControlPointPositionWorld(curve, indexOfControlPoint):
        controlPoint = curve.GetNthControlPointPositionWorld(indexOfControlPoint)
        # Curve points are about 10-to-1 control points.  There are index+1 points in {0, ..., index}.  So, typically
        # numberOfControlPoints = 10 * indexOfControlPoint + 1.
        numberOfCurvePoints = curve.GetClosestCurvePointIndexToPositionWorld(controlPoint) + 1
        print(f"{indexOfControlPoint = }, {numberOfCurvePoints = }")
        distance = curve.GetCurveLengthWorld(0, numberOfCurvePoints)
        return distance

    @staticmethod
    def Matrix3x3ToOrientation(matrix3x3, orientation=np.zeros((4,))):
        vtkQ = vtk.vtkQuaternion[np.float64]()
        vtkQ.FromMatrix3x3(matrix3x3)
        orientation[0] = vtkQ.GetRotationAngleAndAxis(orientation[1:4])
        return orientation

    @staticmethod
    def Matrix3x3ToQuaternion(matrix3x3, quaternion=np.zeros((4,))):
        vtk.vtkMath.Matrix3x3ToQuaternion(matrix3x3, quaternion)
        return quaternion

    @staticmethod
    def OrientationToMatrix3x3(orientation, matrix3x3=np.zeros((3, 3))):
        vtkQ = vtk.vtkQuaternion[np.float64]()
        vtkQ.SetRotationAngleAndAxis(*orientation)
        vtkQ.ToMatrix3x3(matrix3x3)
        return matrix3x3

    @staticmethod
    def OrientationToQuaternion(orientation, quaternion=np.zeros((4,))):
        vtkQ = vtk.vtkQuaternion[np.float64]()
        vtkQ.SetRotationAngleAndAxis(*orientation)
        vtkQ.Get(quaternion)
        return quaternion

    @staticmethod
    def QuaternionToMatrix3x3(quaternion, matrix3x3=np.zeros((3, 3))):
        vtk.vtkMath.QuaternionToMatrix3x3(quaternion, matrix3x3)
        return matrix3x3

    @staticmethod
    def QuaternionToOrientation(quaternion, orientation=np.zeros((4,))):
        vtkQ = vtk.vtkQuaternion[np.float64]()
        vtkQ.Set(*quaternion)
        orientation[0] = vtkQ.GetRotationAngleAndAxis(orientation[1:4])
        return orientation

    @staticmethod
    def MultiplyOrientations(leftOrientation, rightOrientation, resultOrientation=np.zeros((4,))):
        return EndoscopyLogic.Matrix3x3ToOrientation(
            np.matmul(
                EndoscopyLogic.OrientationToMatrix3x3(leftOrientation),
                EndoscopyLogic.OrientationToMatrix3x3(rightOrientation),
            ),
            resultOrientation,
        )

    @staticmethod
    def PlaneFit(points):
        """
        source: https://stackoverflow.com/questions/12299540/plane-fitting-to-4-or-more-xyz-points

        p, n = PlaneFit(points)

        Given `points`, an array of shape (d, ...), representing points in d-dimensional (hyper)space, fit a
        (d-1)-dimensional (hyper)plane to the points.  Return a point `p` on the plane (the point-cloud centroid), and
        the a unit normal vector `n`.
        """

        points = points.reshape((points.shape[0], -1))  # Collapse trailing dimensions
        p = points.mean(axis=1)
        points -= p[:, np.newaxis]  # Recenter on the centroid
        n = np.linalg.svd(np.dot(points, points.T))[0][:, -1]
        return p, n


class EndoscopyPathModel:
    """Create a vtkPolyData for a polyline:
    - Add one point per path point.
    - Add a single polyline
    """

    def __init__(self, resampledCurve, inputMarkupsFiducialNode, outputPathNode=None, cursorType=None):
        """
        :param resampledCurve: resampledCurve generated by EndoscopyLogic
        :param inputMarkupsFiducialNode: input node, just used for naming the output node.
        :param outputPathNode: output model node that stores the path points.
        :param cursorType: can be 'markups' or 'model'. Markups has a number of advantages (radius it is easier to change the size,
          can jump to views by clicking on it, has more visualization options, can be scaled to fixed display size),
          but if some applications relied on having a model node as cursor then this argument can be used to achieve that.
        """

        self.cursorType = "markups" if cursorType is None else cursorType

        points = vtk.vtkPoints()
        polyData = vtk.vtkPolyData()
        polyData.SetPoints(points)

        lines = vtk.vtkCellArray()
        polyData.SetLines(lines)
        linesIDArray = lines.GetData()
        linesIDArray.Reset()
        linesIDArray.InsertNextTuple1(0)

        polygons = vtk.vtkCellArray()
        polyData.SetPolys(polygons)
        idArray = polygons.GetData()
        idArray.Reset()
        idArray.InsertNextTuple1(0)

        for pathIndex in range(resampledCurve.GetNumberOfControlPoints()):
            point = np.zeros((3,))
            resampledCurve.GetNthControlPointPositionWorld(pathIndex, point)
            pointIndex = points.InsertNextPoint(*point)
            linesIDArray.InsertNextTuple1(pointIndex)
            linesIDArray.SetTuple1(0, linesIDArray.GetNumberOfTuples() - 1)
            lines.SetNumberOfCells(1)

        pointsArray = vtk.util.numpy_support.vtk_to_numpy(points.GetData())

        # Create model node
        model = outputPathNode
        if not model:
            model = slicer.mrmlScene.AddNewNodeByClass(
                "vtkMRMLModelNode", slicer.mrmlScene.GenerateUniqueName("Path-%s" % inputMarkupsFiducialNode.GetName())
            )
            model.CreateDefaultDisplayNodes()
            model.GetDisplayNode().SetColor(1, 1, 0)  # yellow

        model.SetAndObservePolyData(polyData)

        # Camera cursor
        cursor = model.GetNodeReference("CameraCursor")
        if not cursor:
            if self.cursorType == "markups":
                # Markups cursor
                cursor = slicer.mrmlScene.AddNewNodeByClass(
                    "vtkMRMLMarkupsFiducialNode",
                    slicer.mrmlScene.GenerateUniqueName("Cursor-%s" % inputMarkupsFiducialNode.GetName()),
                )
                cursor.CreateDefaultDisplayNodes()
                cursor.GetDisplayNode().SetSelectedColor(1, 0, 0)  # red
                cursor.GetDisplayNode().SetSliceProjection(True)
                cursor.AddControlPoint(vtk.vtkVector3d(0, 0, 0), " ")  # do not show any visible label
                cursor.SetNthControlPointLocked(0, True)
            else:
                # Model cursor
                cursor = slicer.mrmlScene.AddNewNodeByClass(
                    "vtkMRMLMarkupsModelNode",
                    slicer.mrmlScene.GenerateUniqueName("Cursor-%s" % inputMarkupsFiducialNode.GetName()),
                )
                cursor.CreateDefaultDisplayNodes()
                cursor.GetDisplayNode().SetColor(1, 0, 0)  # red
                cursor.GetDisplayNode().BackfaceCullingOn()  # so that the camera can see through the cursor from inside
                # Add a sphere as cursor
                sphere = vtk.vtkSphereSource()
                sphere.Update()
                cursor.SetPolyDataConnection(sphere.GetOutputPort())

            model.SetNodeReferenceID("CameraCursor", cursor.GetID())

        # Transform node
        transform = model.GetNodeReference("CameraTransform")
        if not transform:
            transform = slicer.mrmlScene.AddNewNodeByClass(
                "vtkMRMLLinearTransformNode",
                slicer.mrmlScene.GenerateUniqueName("Transform-%s" % inputMarkupsFiducialNode.GetName()),
            )
            model.SetNodeReferenceID("CameraTransform", transform.GetID())
        cursor.SetAndObserveTransformNodeID(transform.GetID())

        self.transform = transform
