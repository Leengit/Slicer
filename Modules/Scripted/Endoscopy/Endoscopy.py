import ctk
import logging
import numpy as np
import qt
import slicer
import vtk
import vtk.util.numpy_support
from slicer.i18n import tr as _
from slicer.i18n import translate


class Endoscopy(slicer.ScriptedLoadableModule.ScriptedLoadableModule):
    """Uses slicer.ScriptedLoadableModule.ScriptedLoadableModule base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def __init__(self, parent):
        slicer.ScriptedLoadableModule.ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = _("Endoscopy")
        self.parent.categories = [translate("qSlicerAbstractCoreModule", "Endoscopy")]
        self.parent.dependencies = []
        self.parent.contributors = ["Steve Pieper (Isomics)", "Harald Scheirich (Kitware)", "Lee Newberg (Kitware)"]
        self.parent.helpText = _("""
Create a path model as a spline interpolation of a set of fiducial points.
Pick the Camera to be modified by the path and the Fiducial List defining the control points.
Clicking "Create model" will make a path model and enable the flythrough panel.
You can manually scroll through the path with the Frame slider. The Play/Pause button toggles animated flythrough.
The Frame Skip slider speeds up the animation by skipping points on the path.
The Frame Delay slider slows down the animation by adding more time between frames.
The View Angle provides is used to approximate the optics of an endoscopy system.
""")
        self.parent.helpText += self.getDefaultModuleDocumentationLink()
        self.parent.acknowledgementText = _("""
This work is supported by PAR-07-249: R01CA131718 NA-MIC Virtual Colonoscopy
(See <a>https://www.na-mic.org/Wiki/index.php/NA-MIC_NCBC_Collaboration:NA-MIC_virtual_colonoscopy</a>)
NA-MIC, NAC, BIRN, NCIGT, and the Slicer Community.
""")


class EndoscopyWidget(slicer.ScriptedLoadableModule.ScriptedLoadableModuleWidget):
    """Uses slicer.ScriptedLoadableModule.ScriptedLoadableModuleWidget base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """

    # TODO: Need to use logic of https://github.com/Slicer/Slicer/pull/6541/files, Lines 465 and following to handle
    # user's use of the new GUI.

    def __init__(self, parent=None):
        slicer.ScriptedLoadableModule.ScriptedLoadableModuleWidget.__init__(self, parent)
        self.transform = None
        self.skip = 0
        self.logic = None
        self.timer = qt.QTimer()
        logging.debug('        self.timer = qt.QTimer()')
        self.timer.setInterval(20)
        self.timer.connect('timeout()', self.flyToNext)
        logging.debug('            self.timer.connect("timeout()", self.flyToNext)')

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
                    pathFormLayout.addRow("Output Model:", outputPathNodeSelector)
                createPathButton = qt.QPushButton("Create model")
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
                flythroughFrameSlider = ctk.ctkSliderWidget()
                    flythroughFrameSlider.connect("valueChanged(double)", self.flythroughFrameSliderValueChanged)
                    flythroughFormLayout.addRow("Frame:", flythroughFrameSlider)
                flythroughFrameSkipSlider = ctk.ctkSliderWidget()
                    flythroughFrameSkipSlider.connect("valueChanged(double)", self.flythroughFrameSkipSliderValueChanged)
                    flythroughFormLayout.addRow("Frame skip:", flythroughFrameSkipSlider)
                flythroughFrameDelaySlider = ctk.ctkSliderWidget()
                    flythroughFrameDelaySlider.connect("valueChanged(double)", self.flythroughFrameDelaySliderValueChanged)
                    flythroughFormLayout.addRow("Frame delay:", flythroughFrameDelaySlider)
                flythroughViewAngleSlider = ctk.ctkSliderWidget()
                    flythroughViewAngleSlider.connect("valueChanged(double)", self.flythroughViewAngleSliderValueChanged)
                    flythroughFormLayout.addRow("View Angle:", flythroughViewAngleSlider)
                flythroughPlayButton = qt.QPushButton("Play")
                    flythroughPlayButton.connect("toggled(bool)", self.onPlayButtonToggled)
                    flythroughFormLayout.addRow(flythroughPlayButton)
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
        logging.debug('self.layout.addStretch(1)')

        self.cameraNodeSelector.setMRMLScene(slicer.mrmlScene)
        self.inputFiducialNodeSelector.setMRMLScene(slicer.mrmlScene)
        self.outputPathNodeSelector.setMRMLScene(slicer.mrmlScene)

    def setupPathUI(self):
        # Path collapsible button
        pathCollapsibleButton = ctk.ctkCollapsibleButton()
        logging.debug('pathCollapsibleButton = ctk.ctkCollapsibleButton()')
        pathCollapsibleButton.text = _("Path")
        self.layout.addWidget(pathCollapsibleButton)
        logging.debug('    self.layout.addWidget(pathCollapsibleButton)')

        # Layout within the path collapsible button
        pathFormLayout = qt.QFormLayout(pathCollapsibleButton)
        logging.debug('    pathFormLayout = qt.QFormLayout(pathCollapsibleButton)')

        # Camera node selector
        cameraNodeSelector = slicer.qMRMLNodeComboBox()
        logging.debug('    cameraNodeSelector = slicer.qMRMLNodeComboBox()')
        cameraNodeSelector.objectName = 'cameraNodeSelector'
        cameraNodeSelector.toolTip = _("Select a camera that will fly along this path.")
        cameraNodeSelector.nodeTypes = ['vtkMRMLCameraNode']
        cameraNodeSelector.noneEnabled = False
        cameraNodeSelector.addEnabled = False
        cameraNodeSelector.removeEnabled = False
        cameraNodeSelector.connect('currentNodeChanged(bool)', self.enableOrDisableCreateButton)
        logging.debug('        cameraNodeSelector.connect("currentNodeChanged(bool)", self.enableOrDisableCreateButton)')
        cameraNodeSelector.connect('currentNodeChanged(vtkMRMLNode*)', self.setCameraNode)
        logging.debug('        cameraNodeSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.setCameraNode)')
        pathFormLayout.addRow(_("Camera:"), cameraNodeSelector)
        logging.debug('        pathFormLayout.addRow("Camera:", cameraNodeSelector)')
        self.cameraNodeSelector = cameraNodeSelector

        # Input fiducial node selector
        inputFiducialNodeSelector = slicer.qMRMLNodeComboBox()
        logging.debug('    inputFiducialNodeSelector = slicer.qMRMLNodeComboBox()')
        inputFiducialNodeSelector.objectName = 'inputFiducialNodeSelector'
        inputFiducialNodeSelector.toolTip = _("Select a fiducial list to define control points for the path.")
        inputFiducialNodeSelector.nodeTypes = ['vtkMRMLMarkupsFiducialNode', 'vtkMRMLMarkupsCurveNode']
        inputFiducialNodeSelector.noneEnabled = False
        inputFiducialNodeSelector.addEnabled = False
        inputFiducialNodeSelector.removeEnabled = False
        inputFiducialNodeSelector.connect('currentNodeChanged(bool)', self.enableOrDisableCreateButton)
        logging.debug('        inputFiducialNodeSelector.connect("currentNodeChanged(bool)", self.enableOrDisableCreateButton)')
        inputFiducialNodeSelector.connect('currentNodeChanged(vtkMRMLNode*)', self.setFiducialNode)
        logging.debug('        inputFiducialNodeSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.setFiducialNode)')
        pathFormLayout.addRow(_("Input Fiducial Nodes:"), inputFiducialNodeSelector)
        logging.debug('        pathFormLayout.addRow("Input Fiducial Nodes:", inputFiducialNodeSelector)')
        self.inputFiducialNodeSelector = inputFiducialNodeSelector

        # Output path node selector
        outputPathNodeSelector = slicer.qMRMLNodeComboBox()
        logging.debug('    outputPathNodeSelector = slicer.qMRMLNodeComboBox()')
        outputPathNodeSelector.objectName = 'outputPathNodeSelector'
        outputPathNodeSelector.toolTip = _("Select a fiducial list to define control points for the path.")
        outputPathNodeSelector.nodeTypes = ['vtkMRMLModelNode']
        outputPathNodeSelector.noneEnabled = False
        outputPathNodeSelector.addEnabled = True
        outputPathNodeSelector.removeEnabled = True
        outputPathNodeSelector.renameEnabled = True
        outputPathNodeSelector.connect('currentNodeChanged(bool)', self.enableOrDisableCreateButton)
        logging.debug('        outputPathNodeSelector.connect("currentNodeChanged(bool)", self.enableOrDisableCreateButton)')
        pathFormLayout.addRow(_("Output Model:"), outputPathNodeSelector)
        logging.debug('        pathFormLayout.addRow("Output Model:", outputPathNodeSelector)')
        self.outputPathNodeSelector = outputPathNodeSelector

        # CreatePath button
        createPathButton = qt.QPushButton(_("Create model"))
        logging.debug('    createPathButton = qt.QPushButton("Create model")')
        createPathButton.toolTip = _("Create the path.")
        createPathButton.enabled = False
        createPathButton.connect('clicked()', self.onCreatePathButtonClicked)
        logging.debug('        createPathButton.connect("clicked()", self.onCreatePathButtonClicked)')
        pathFormLayout.addRow(createPathButton)
        logging.debug('        pathFormLayout.addRow(createPathButton)')
        self.createPathButton = createPathButton

    def setupKeyframeUI(self):
        keyframeCollapsibleButton = ctk.ctkCollapsibleButton()
        logging.debug('keyframeCollapsibleButton = ctk.ctkCollapsibleButton()')
        keyframeCollapsibleButton.text = _("Keyframes")
        keyframeCollapsibleButton.enabled = False
        self.layout.addWidget(keyframeCollapsibleButton)
        logging.debug('    self.layout.addWidget(keyframeCollapsibleButton)')
        self.keyframeCollapsibleButton = keyframeCollapsibleButton

        keyframeLayout = qt.QFormLayout(keyframeCollapsibleButton)
        logging.debug('    keyframeLayout = qt.QFormLayout(keyframeCollapsibleButton)')

        # KeyFrame slider
        keyframeSlider = ctk.ctkSliderWidget()
        logging.debug('    keyframeSlider = ctk.ctkSliderWidget()')
        keyframeSlider.decimals = 0
        keyframeSlider.minimum = 0
        keyframeSlider.connect('valueChanged(double)', self.selectControlPoint)
        logging.debug('        keyframeSlider.connect("valueChanged(double)", self.selectControlPoint)')
        keyframeLayout.addRow(_("Frame:"), keyframeSlider)
        logging.debug('        keyframeLayout.addRow("Frame:", keyframeSlider)')
        self.keyframeSlider = keyframeSlider

        refreshButton = qt.QPushButton(_("Refresh Rotations"))
        logging.debug('    refreshButton = qt.QPushButton("Refresh Rotations")')
        refreshButton.connect('clicked()', self.refreshOrientations)
        logging.debug('        refreshButton.connect("clicked()", self.refreshOrientations)')
        keyframeLayout.addRow(refreshButton)
        logging.debug('        keyframeLayout.addRow(refreshButton)')

    def setupFlythroughUI(self):
        # Flythrough collapsible button
        flythroughCollapsibleButton = ctk.ctkCollapsibleButton()
        logging.debug('flythroughCollapsibleButton = ctk.ctkCollapsibleButton()')
        flythroughCollapsibleButton.text = _("Flythrough")
        flythroughCollapsibleButton.enabled = False
        self.layout.addWidget(flythroughCollapsibleButton)
        logging.debug('    self.layout.addWidget(flythroughCollapsibleButton)')
        self.flythroughCollapsibleButton = flythroughCollapsibleButton

        # Layout within the Flythrough collapsible button
        flythroughFormLayout = qt.QFormLayout(flythroughCollapsibleButton)
        logging.debug('    flythroughFormLayout = qt.QFormLayout(flythroughCollapsibleButton)')

        # Frame slider
        flythroughFrameSlider = ctk.ctkSliderWidget()
        logging.debug('    flythroughFrameSlider = ctk.ctkSliderWidget()')
        flythroughFrameSlider.decimals = 0
        flythroughFrameSlider.connect('valueChanged(double)', self.flythroughFrameSliderValueChanged)
        logging.debug('        flythroughFrameSlider.connect("valueChanged(double)", self.flythroughFrameSliderValueChanged)')
        flythroughFormLayout.addRow(_("Frame:"), flythroughFrameSlider)
        logging.debug('        flythroughFormLayout.addRow("Frame:", flythroughFrameSlider)')
        self.flythroughFrameSlider = flythroughFrameSlider

        # Frame skip slider
        flythroughFrameSkipSlider = ctk.ctkSliderWidget()
        logging.debug('    flythroughFrameSkipSlider = ctk.ctkSliderWidget()')
        flythroughFrameSkipSlider.decimals = 0
        flythroughFrameSkipSlider.minimum = 0
        flythroughFrameSkipSlider.maximum = 50
        flythroughFrameSkipSlider.connect('valueChanged(double)', self.flythroughFrameSkipSliderValueChanged)
        logging.debug(
            '        flythroughFrameSkipSlider.connect("valueChanged(double)", '
            + 'self.flythroughFrameSkipSliderValueChanged)',
        )
        flythroughFormLayout.addRow(_("Frame skip:"), flythroughFrameSkipSlider)
        logging.debug('        flythroughFormLayout.addRow("Frame skip:", flythroughFrameSkipSlider)')

        # Frame delay slider
        flythroughFrameDelaySlider = ctk.ctkSliderWidget()
        logging.debug('    flythroughFrameDelaySlider = ctk.ctkSliderWidget()')
        flythroughFrameDelaySlider.decimals = 0
        flythroughFrameDelaySlider.minimum = 5
        flythroughFrameDelaySlider.maximum = 100
        flythroughFrameDelaySlider.suffix = " ms"
        flythroughFrameDelaySlider.value = 20
        flythroughFrameDelaySlider.connect('valueChanged(double)', self.flythroughFrameDelaySliderValueChanged)
        logging.debug(
            '        flythroughFrameDelaySlider.connect("valueChanged(double)", '
            + 'self.flythroughFrameDelaySliderValueChanged)',
        )
        flythroughFormLayout.addRow(_("Frame delay:"), flythroughFrameDelaySlider)
        logging.debug('        flythroughFormLayout.addRow("Frame delay:", flythroughFrameDelaySlider)')

        # View angle slider
        flythroughViewAngleSlider = ctk.ctkSliderWidget()
        logging.debug('    flythroughViewAngleSlider = ctk.ctkSliderWidget()')
        flythroughViewAngleSlider.decimals = 0
        flythroughViewAngleSlider.minimum = 30
        flythroughViewAngleSlider.maximum = 180
        flythroughViewAngleSlider.connect('valueChanged(double)', self.flythroughViewAngleSliderValueChanged)
        logging.debug(
            '        flythroughViewAngleSlider.connect("valueChanged(double)", '
            + 'self.flythroughViewAngleSliderValueChanged)',
        )
        flythroughFormLayout.addRow(_("View Angle:"), flythroughViewAngleSlider)
        logging.debug('        flythroughFormLayout.addRow("View Angle:", flythroughViewAngleSlider)')
        self.flythroughViewAngleSlider = flythroughViewAngleSlider

        # Play button
        flythroughPlayButton = qt.QPushButton(_("Play"))
        logging.debug('    flythroughPlayButton = qt.QPushButton("Play")')
        flythroughPlayButton.toolTip = _("Fly through path.")
        flythroughPlayButton.checkable = True
        flythroughPlayButton.connect('toggled(bool)', self.onPlayButtonToggled)
        logging.debug('        flythroughPlayButton.connect("toggled(bool)", self.onPlayButtonToggled)')
        flythroughFormLayout.addRow(flythroughPlayButton)
        logging.debug('        flythroughFormLayout.addRow(flythroughPlayButton)')
        self.flythroughPlayButton = flythroughPlayButton

    def setupCursorNode(self):
        # TODO: Is this function doing everything it needs to do?
        self.cursorNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsPlaneNode", "EndoscopyCursor")
        logging.debug('    self.cursorNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsPlaneNode", "EndoscopyCursor")')

        # TODO: Instead call selectControlPoint(0)?
        where = (
            # TODO: Maybe access self.logic.inputCurve instead of self.fiducialNode, here and elsewhere?
            self.fiducialNode.GetNthControlPointPositionWorld(0)
            if self.fiducialNode and self.fiducialNode.GetNumberOfControlPoints() > 0
            else [0, 0, 0]
        )
        self.cursorNode.AddControlPointWorld(*where)
        self.cursorNode.SetNthControlPointVisibility(0, False)
        # hack to hide sphere glyph that can also be used for translating by grabbing with mouse.  We don't want the
        # user to directly translate these planes.
        logging.debug(f"{self.cursorNode.GetDisplayNode().GetGlyphSize() = }")
        logging.debug(f"{self.cursorNode.GetDisplayNode().GetGlyphScale() = }")
        # self.cursorNode.GetDisplayNode().SetGlyphScale(0.0001)
        self.cursorNode.SetSize(10.0, 10.0)
        display = self.cursorNode.GetMarkupsDisplayNode()
        # TODO: How do we hide the plane itself (while showing only the rotation handles)?
        display.SetGlyphScale(0.0001)
        display.SetTranslationHandleVisibility(False)
        display.SetScaleHandleVisibility(False)
        display.SetRotationHandleVisibility(True)
        display.SetPropertiesLabelVisibility(False)

        tag = self.cursorNode.AddObserver(vtk.vtkCommand.ModifiedEvent, self.cursorModified)
        self.cursorNodeObserverTags.append(tag)
        logging.debug(
            'self.cursorNodeObserverTags.append(self.cursorNode.AddObserver(vtk.vtkCommand.ModifiedEvent, '
            + 'self.cursorModified))',
        )
        # We've placed the control point; don't have the user place more
        interactionNode = slicer.mrmlScene.GetNodeByID("vtkMRMLInteractionNodeSingleton")
        interactionNode.SwitchToViewTransformMode()
        interactionNode.SetPlaceModePersistence(0)

    def cleanup(self):
        if self.logic:
            self.logic.cleanup()
        self.logic = None

        if self.cameraNode:
            for tag in self.cameraNodeObserverTags:
                self.cameraNode.RemoveObserver(tag)
        self.cameraNodeObserverTags = []
        self.cameraNode = None

        if self.camera:
            for tag in self.cameraObserverTags:
                self.camera.RemoveObserver(tag)
        self.cameraObserverTags = []
        self.camera = None

        if self.cursorNode:
            for tag in self.cursorNodeObserverTags:
                self.cursorNode.RemoveObserver(tag)
        self.cursorNodeObserverTags = []
        self.cursorNode = None

        if self.fiducialNode:
            for tag in self.fiducialNodeObserverTags:
                self.fiducialNode.RemoveObserver(tag)
        self.fiducialNodeObserverTags = []
        self.fiducialNode = None

        slicer.ScriptedLoadableModule.ScriptedLoadableModuleWidget.cleanup(self)

    def setCameraNode(self, newCameraNode):
        """Allow to set the current camera node.
        Connected to signal 'currentNodeChanged()' emitted by camera node selector."""

        #  Remove previous observers
        if self.cameraNode:
            for tag in self.cameraNodeObserverTags:
                self.cameraNode.RemoveObserver(tag)
            self.cameraNodeObserverTags = []
        if self.camera:
            for tag in self.cameraObserverTags:
                self.camera.RemoveObserver(tag)
            self.cameraObserverTags = []

        newCamera = None
        if newCameraNode:
            newCamera = newCameraNode.GetCamera()
            # Add CameraNode ModifiedEvent observer
            tag = newCameraNode.AddObserver(vtk.vtkCommand.ModifiedEvent, self.onCameraNodeModified)
            self.cameraNodeObserverTags.append(tag)
            logging.debug(
                'self.cameraNodeObserverTags.append(newCameraNode.AddObserver(vtk.vtkCommand.ModifiedEvent, '
                + 'self.onCameraNodeModified))',
            )
            # Add Camera ModifiedEvent observer
            tag = newCamera.AddObserver(vtk.vtkCommand.ModifiedEvent, self.onCameraNodeModified)
            self.cameraObserverTags.append(tag)
            logging.debug(
                'self.cameraObserverTags.append(newCamera.AddObserver(vtk.vtkCommand.ModifiedEvent, '
                + 'self.onCameraNodeModified))',
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
            tag = newFiducialNode.AddObserver(vtk.vtkCommand.ModifiedEvent, self.onFiducialNodeModified)
            self.fiducialNodeObserverTags.append(tag)
            logging.debug(
                'self.fiducialNodeObserverTags.append(newFiducialNode.AddObserver(vtk.vtkCommand.ModifiedEvent, '
                + 'self.onFiducialNodeModified))',
            )

            # TODO: We probably do not want to lose camera orientation information stored in self.logic, so rebuilding
            # self.logic from scratch might not be appropriate here.
            if self.logic:
                self.logic.cleanup()
            self.logic = EndoscopyLogic(newFiducialNode)

            if self.logic.inputCurve and self.logic.inputCurve.GetNumberOfControlPoints() > 0:
                self.selectControlPoint(0)
                # TODO: Maybe add observer tag so user can select control point with mouse?:
                # self.fiducialNodeObserverTags.extend(
                #     [
                #         newFiducialNode.AddObserver(vtk.vtkCommand.ModifiedEvent, self.controlPointsModified),
                #         newFiducialNode.AddObserver(slicer.vtkMRMLMarkupsNode.PointModifiedEvent, self.controlPointModified),
                #     ]
                # )

            # keyframeSlider selects a control point (not a segment) so index goes up to n - 1
            self.keyframeSlider.maximum = newFiducialNode.GetNumberOfControlPoints() - 1
        else:
            self.flythroughCollapsibleButton.enabled = False
            self.keyframeCollapsibleButton.enabled = False
            self.keyframeSlider.maximum = 0

        self.fiducialNode = newFiducialNode

        # Update UI
        self.updateWidgetFromMRML()

    def updateWidgetFromMRML(self):
        if self.camera:
            self.flythroughViewAngleSlider.value = self.camera.GetViewAngle()
        if self.cameraNode:
            pass
        if self.fiducialNode:
            self.keyframeSlider.maximum = self.fiducialNode.GetNumberOfControlPoints() - 1
            # TODO: Are there other widgets that we should update at this point?

    def onCameraModified(self, observer, eventid):
        self.updateWidgetFromMRML()

    def onCameraNodeModified(self, observer, eventid):
        self.updateWidgetFromMRML()

    def enableOrDisableCreateButton(self):
        """Connected to both the fiducial and camera node selector. It allows to
        enable or disable the 'Create model' button."""
        self.createPathButton.enabled = (
            self.cameraNodeSelector.currentNode()
            and self.inputFiducialNodeSelector.currentNode()
            and self.outputPathNodeSelector.currentNode(),
        )

    def onFiducialNodeModified(self, observer, eventid):
        """If the fiducial was changed we need to repopulate the keyframe UI"""
        # Hack rebuild path just to get the new data
        if self.fiducialNode:
            if self.logic:
                self.logic.cleanup()
            self.logic = EndoscopyLogic(self.fiducialNode)
            # keyframeSlider selects a control point (not a segment) so index goes up to self.logic.n - 1
            self.keyframeSlider.maximum = self.logic.n - 1

    def onCreatePathButtonClicked(self):
        """Connected to 'Create model' button. It allows to:
        - compute the path
        - create the associated model"""

        fiducialNode = self.inputFiducialNodeSelector.currentNode()
        outputPathNode = self.outputPathNodeSelector.currentNode()
        logging.debug("Calculating Path...")
        if self.logic:
            self.logic.cleanup()
        self.logic = EndoscopyLogic(fiducialNode)
        numberOfControlPoints = self.logic.resampledCurve.GetNumberOfControlPoints()
        logging.debug(f"-> Computed path contains {numberOfControlPoints} elements")

        logging.debug("Create model...")
        model = EndoscopyPathModel(self.logic.resampledCurve, fiducialNode, outputPathNode)
        logging.debug("-> Model created")

        # Update frame slider range
        self.keyframeSlider.maximum = max(0, self.logic.inputCurve.GetNumberOfControlPoints() - 1)
        self.flythroughFrameSlider.maximum = max(0, numberOfControlPoints - 2)

        # Update flythrough variables
        self.camera = self.camera
        self.transform = model.transform
        self.planeNormal = self.logic.planeNormal

        # Enable / Disable flythrough button
        enable = numberOfControlPoints > 1
        self.flythroughCollapsibleButton.enabled = enable
        self.keyframeCollapsibleButton.enabled = enable

        # Now that we have a path, we give the user the option to change the camera orientations
        self.setupCursorNode()
        # TODO: Should we call refreshOrientations here?
        self.refreshOrientations()

    def flythroughFrameSliderValueChanged(self, newValue):
        self.flyTo(int(newValue))

    def flythroughFrameSkipSliderValueChanged(self, newValue):
        self.skip = int(newValue)

    def flythroughFrameDelaySliderValueChanged(self, newValue):
        self.timer.setInterval(newValue)

    def flythroughViewAngleSliderValueChanged(self, newValue):
        if self.cameraNode:
            self.cameraNode.GetCamera().SetViewAngle(newValue)

    def onPlayButtonToggled(self, checked):
        if checked:
            self.timer.start()
            self.flythroughPlayButton.text = _("Stop")
        else:
            self.timer.stop()
            self.flythroughPlayButton.text = _("Play")

    def refreshOrientations(self):
        # TODO: What should this function do?  Write me.
        # TODO: Do something with the cursorNode?
        logging.debug("refreshOrientations called")

    def selectControlPoint(self, pathPointIndex):
        pathPointIndex = int(pathPointIndex)
        logging.debug(
            f"selectControlPoint called for Frame {int(self.keyframeSlider.value)}"
            + f" out of {self.logic.inputCurve.GetNumberOfControlPoints()}",
        )
        position = self.logic.inputCurve.GetNthControlPointPositionWorld(pathPointIndex)
        flythroughFrameSliderValue = self.logic.resampledCurve.GetClosestCurvePointIndexToPositionWorld(position)
        flythroughFrameSliderValue //= self.logic.resampledCurve.GetNumberOfPointsPerInterpolatingSegment()
        # If we are currently playing a flythrough, end it.
        self.flythroughPlayButton.setChecked(False)
        # Go to the selected frame
        self.flythroughFrameSlider.value = flythroughFrameSliderValue  # Calls self.flyTo

        if self.cursorNode:
            self.cursorNode.SetNthControlPointPositionWorld(0, position)
            # TODO: Fetch current orientation and set the cursorNode and camera accordingly.  Perhaps including:
            # TODO: self.cursorNode.SetAxes(self.orientations[index][0], self.orientations[index][1], self.orientations[index][2])

    def controlPointsModified(self, observer, eventid):
        # TODO: What should this function do?  Write me.
        logging.debug("controlPointsModified called")

    def controlPointModified(self, observer, eventid):
        # TODO: What should this function do?  Write me.
        logging.debug("controlPointModified called")

    def cursorModified(self, observer, eventid):
        logging.debug("cursorModified called")
        toParent = vtk.vtkMatrix4x4()
        self.cursorNode.GetObjectToWorldMatrix(toParent)
        spatialMatrix3x3 = np.zeros((3, 3))
        for i in range(3):
            for j in range(3):
                spatialMatrix3x3[i, j] = toParent.GetElement(i, j)
        spatialOrientation = EndoscopyLogic.Matrix3x3ToOrientation(spatialMatrix3x3)
        keyframeIndex = int(self.keyframeSlider.value)
        self.logic.inputCurve.SetNthControlPointOrientation(keyframeIndex, *spatialOrientation)
        # TODO: Maybe rebuild quaternion interpolator.
        # TODO: Maybe reorient camera by calling self.flyTo.  (Can we re-orient while we are still holding the
        # vtkMRMLMarkupsPlaneNode rotation handle?)

    def flyToNext(self):
        currentStep = self.flythroughFrameSlider.value
        nextStep = currentStep + self.skip + 1
        if nextStep >= self.logic.resampledCurve.GetNumberOfControlPoints() - 1:
            nextStep = 0
        self.flythroughFrameSlider.value = nextStep

    def flyTo(self, pathPointIndex):
        if self.logic.resampledCurve is None:
            return

        pathPointIndex = int(pathPointIndex)
        cameraPosition = np.zeros((3,))
        self.logic.resampledCurve.GetNthControlPointPositionWorld(pathPointIndex, cameraPosition)
        focalPointPosition = np.zeros((3,))
        self.logic.resampledCurve.GetNthControlPointPositionWorld(pathPointIndex + 1, focalPointPosition)

        defaultOrientation = self.logic.getDefaultOrientation(self.logic.resampledCurve, pathPointIndex)
        relativeOrientation = np.zeros((4,))
        self.logic.resampledCurve.GetNthControlPointOrientation(pathPointIndex, relativeOrientation)
        resultMatrix = np.matmul(
            EndoscopyLogic.OrientationToMatrix3x3(relativeOrientation),
            EndoscopyLogic.OrientationToMatrix3x3(defaultOrientation),
        )

        # Build a 4x4 matrix from the 3x3 matrix and the camera position
        toParent = vtk.vtkMatrix4x4()
        toParent.SetElement(3, 3, 1.0)
        for j in range(3):
            for i in range(3):
                toParent.SetElement(i, j, resultMatrix[i, j])
            toParent.SetElement(3, j, 0.0)
            toParent.SetElement(j, 3, cameraPosition[j])

        # Work on camera and cameraNode
        wasModified = self.cameraNode.StartModify()
        self.camera.SetPosition(*cameraPosition)
        self.camera.SetFocalPoint(*focalPointPosition)
        self.camera.OrthogonalizeViewUp()
        self.transform.SetMatrixTransformToParent(toParent)
        self.cameraNode.ResetClippingRange()
        self.cameraNode.EndModify(wasModified)


class EndoscopyLogic:
    """Compute path given a list of fiducial nodes.
    Path is stored in 'path' member variable as a numpy array.
    If a point list is received then curve points are generated using Hermite spline interpolation.
    See https://en.wikipedia.org/wiki/Cubic_Hermite_spline

    Example:
      self.logic = EndoscopyLogic(inputMarkupsFiducialNode)
      print(f"computed path has {self.logic.resampledCurve.GetNumberOfControlPoints()} elements")

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
            and self.setCameraOrientationsFromInputCurve(),
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
            # slicer.util.errorDisplay("You need at least 2 control points in order to make a fly through.", "Run Error")
            return False

        # Copy everything from the input
        self.inputCurve.Copy(inputMarkupsFiducialNode)
        logging.debug("Created self.inputCurve")
        return True

    def setCameraPositionsFromInputCurve(self):
        # We now have the user's input as a curve.  Let's get equidistant points to represent the curve.
        resampledPoints = vtk.vtkPoints()
        slicer.vtkMRMLMarkupsCurveNode.ResamplePoints(
            self.inputCurve.GetCurvePointsWorld(),
            resampledPoints,
            self.dl,
            self.inputCurve.GetCurveClosed(),
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
        # # Using a modified Kochanek basis
        # quaternionInterpolator.SetInterpolationTypeToSpline()
        # Using linear spherical interpolation
        quaternionInterpolator.SetInterpolationTypeToLinear()
        # If the curve is closed, put the first orientation also at the end
        lastN = n if self.inputCurve.GetClassName() == "vtkMRMLMarkupsClosedCurveNode" else n - 1
        for i in range(n):
            # TODO: For the moment assume that all orientations have been supplied by the user.  This loop should
            # instead include only user-supplied interpolations.  Those that are not supplied by the user, and thus are
            # in need of being computed via interpolation, should not be supplied via .AddQuaternion().
            supplied = True
            if supplied or i == 0 or i == lastN:
                distanceAlongInputCurve = EndoscopyLogic.distanceAlongCurveOfNthControlPointPositionWorld(
                    self.inputCurve,
                    i,
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
        # logging.debug(f"getDefaultOrientation[{pathIndex}] = ", end="")
        n = curve.GetNumberOfControlPoints()
        # If the curve is not closed then the last control point has the same orientation as its previous control point
        if pathIndex == n - 1 and curve.GetClassName() != "vtkMRMLMarkupsClosedCurveNode":
            pathIndex -= 1
        nextPathIndex = (pathIndex + 1) % n
        cameraPosition = np.zeros((3,))
        curve.GetNthControlPointPositionWorld(pathIndex, cameraPosition)
        focalPointPosition = np.zeros((3,))
        curve.GetNthControlPointPositionWorld(nextPathIndex, focalPointPosition)
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
        # logging.debug(repr(orientation))
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
        # Curve points are about 10-to-1 control points.  There are index + 1 points in {0, ..., index}.  So, typically
        # numberOfControlPoints = 10 * indexOfControlPoint + 1.
        numberOfCurvePoints = curve.GetClosestCurvePointIndexToPositionWorld(controlPoint) + 1
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
        # Choose the normal to be in the direction of increasing coordinate value
        primary_direction = np.abs(n).argmax()
        if n[primary_direction] < 0.0:
            n *= -1.0
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
        :param cursorType: can be 'markups' or 'model'. Markups has a number of advantages (radius it is easier to
          change the size, can jump to views by clicking on it, has more visualization options, can be scaled to fixed
          display size), but if some applications relied on having a model node as cursor then this argument can be used
          to achieve that.
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
                "vtkMRMLModelNode",
                slicer.mrmlScene.GenerateUniqueName("Path-%s" % inputMarkupsFiducialNode.GetName()),
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
