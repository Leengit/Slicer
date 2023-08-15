import ctk
import numpy as np
import qt
import slicer
import vtk
import vtk.util.numpy_support

from slicer.ScriptedLoadableModule import *

"""
Note:
* `orientation` = (angle, *axis), where angle is in degrees and axis is the unit 3D-vector for the axis of rotation.
* `quaternion` = (cos(angle/2), *axis * sin(angle/2))
* `matrix` = matrix with columns x, y, and z, which are unit vectors for the rotated frame
"""

#
# Endoscopy
#

class Endoscopy(ScriptedLoadableModule):
    """Uses ScriptedLoadableModule base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
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


#
# qSlicerPythonModuleExampleWidget
#

class EndoscopyWidget(ScriptedLoadableModuleWidget):
    """Uses ScriptedLoadableModuleWidget base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def __init__(self, parent=None):
        ScriptedLoadableModuleWidget.__init__(self, parent)
        self.cameraNode = None
        self.cameraNodeObserverTag = None
        self.cameraObserverTag = None
        # Flythough variables
        self.transform = None
        self.path = None
        self.camera = None
        self.skip = 0
        self.timer = qt.QTimer()
        self.timer.setInterval(20)
        self.timer.connect('timeout()', self.flyToNext)

    def setup(self):
        # TODO: Also set up GUI for camera orientations (and translations?) during fly through.  See "Files Changed" in
        # https://github.com/Slicer/Slicer/pull/6541/.

        ScriptedLoadableModuleWidget.setup(self)

        # Path collapsible button
        pathCollapsibleButton = ctk.ctkCollapsibleButton()
        pathCollapsibleButton.text = "Path"
        self.layout.addWidget(pathCollapsibleButton)

        # Layout within the path collapsible button
        pathFormLayout = qt.QFormLayout(pathCollapsibleButton)

        # Camera node selector
        cameraNodeSelector = slicer.qMRMLNodeComboBox()
        cameraNodeSelector.objectName = 'cameraNodeSelector'
        cameraNodeSelector.toolTip = "Select a camera that will fly along this path."
        cameraNodeSelector.nodeTypes = ['vtkMRMLCameraNode']
        cameraNodeSelector.noneEnabled = False
        cameraNodeSelector.addEnabled = False
        cameraNodeSelector.removeEnabled = False
        cameraNodeSelector.connect('currentNodeChanged(bool)', self.enableOrDisableCreateButton)
        cameraNodeSelector.connect('currentNodeChanged(vtkMRMLNode*)', self.setCameraNode)
        pathFormLayout.addRow("Camera:", cameraNodeSelector)

        # Input fiducials node selector
        inputFiducialsNodeSelector = slicer.qMRMLNodeComboBox()
        inputFiducialsNodeSelector.objectName = 'inputFiducialsNodeSelector'
        inputFiducialsNodeSelector.toolTip = "Select a fiducial list to define control points for the path."
        inputFiducialsNodeSelector.nodeTypes = ['vtkMRMLMarkupsFiducialNode', 'vtkMRMLMarkupsCurveNode']
        inputFiducialsNodeSelector.noneEnabled = False
        inputFiducialsNodeSelector.addEnabled = False
        inputFiducialsNodeSelector.removeEnabled = False
        inputFiducialsNodeSelector.connect('currentNodeChanged(bool)', self.enableOrDisableCreateButton)
        pathFormLayout.addRow("Input Fiducials:", inputFiducialsNodeSelector)

        # Output path node selector
        outputPathNodeSelector = slicer.qMRMLNodeComboBox()
        outputPathNodeSelector.objectName = 'outputPathNodeSelector'
        outputPathNodeSelector.toolTip = "Select a fiducial list to define control points for the path."
        outputPathNodeSelector.nodeTypes = ['vtkMRMLModelNode']
        outputPathNodeSelector.noneEnabled = False
        outputPathNodeSelector.addEnabled = True
        outputPathNodeSelector.removeEnabled = True
        outputPathNodeSelector.renameEnabled = True
        outputPathNodeSelector.connect('currentNodeChanged(bool)', self.enableOrDisableCreateButton)
        pathFormLayout.addRow("Output Path:", outputPathNodeSelector)

        # CreatePath button
        createPathButton = qt.QPushButton("Create path")
        createPathButton.toolTip = "Create the path."
        createPathButton.enabled = False
        pathFormLayout.addRow(createPathButton)
        createPathButton.connect('clicked()', self.onCreatePathButtonClicked)

        # Flythrough collapsible button
        flythroughCollapsibleButton = ctk.ctkCollapsibleButton()
        flythroughCollapsibleButton.text = "Flythrough"
        flythroughCollapsibleButton.enabled = False
        self.layout.addWidget(flythroughCollapsibleButton)

        # Layout within the Flythrough collapsible button
        flythroughFormLayout = qt.QFormLayout(flythroughCollapsibleButton)

        # Frame slider
        frameSlider = ctk.ctkSliderWidget()
        frameSlider.connect('valueChanged(double)', self.frameSliderValueChanged)
        frameSlider.decimals = 0
        flythroughFormLayout.addRow("Frame:", frameSlider)

        # Frame skip slider
        frameSkipSlider = ctk.ctkSliderWidget()
        frameSkipSlider.connect('valueChanged(double)', self.frameSkipSliderValueChanged)
        frameSkipSlider.decimals = 0
        frameSkipSlider.minimum = 0
        frameSkipSlider.maximum = 50
        flythroughFormLayout.addRow("Frame skip:", frameSkipSlider)

        # Frame delay slider
        frameDelaySlider = ctk.ctkSliderWidget()
        frameDelaySlider.connect('valueChanged(double)', self.frameDelaySliderValueChanged)
        frameDelaySlider.decimals = 0
        frameDelaySlider.minimum = 5
        frameDelaySlider.maximum = 100
        frameDelaySlider.suffix = " ms"
        frameDelaySlider.value = 20
        flythroughFormLayout.addRow("Frame delay:", frameDelaySlider)

        # View angle slider
        viewAngleSlider = ctk.ctkSliderWidget()
        viewAngleSlider.connect('valueChanged(double)', self.viewAngleSliderValueChanged)
        viewAngleSlider.decimals = 0
        viewAngleSlider.minimum = 30
        viewAngleSlider.maximum = 180
        flythroughFormLayout.addRow("View Angle:", viewAngleSlider)

        # Play button
        playButton = qt.QPushButton("Play")
        playButton.toolTip = "Fly through path."
        playButton.checkable = True
        flythroughFormLayout.addRow(playButton)
        playButton.connect('toggled(bool)', self.onPlayButtonToggled)

        # Add vertical spacer
        self.layout.addStretch(1)

        # Set local var as instance attribute
        self.cameraNodeSelector = cameraNodeSelector
        self.inputFiducialsNodeSelector = inputFiducialsNodeSelector
        self.outputPathNodeSelector = outputPathNodeSelector
        self.createPathButton = createPathButton
        self.flythroughCollapsibleButton = flythroughCollapsibleButton
        self.frameSlider = frameSlider
        self.viewAngleSlider = viewAngleSlider
        self.playButton = playButton

        cameraNodeSelector.setMRMLScene(slicer.mrmlScene)
        inputFiducialsNodeSelector.setMRMLScene(slicer.mrmlScene)
        outputPathNodeSelector.setMRMLScene(slicer.mrmlScene)

    def setCameraNode(self, newCameraNode):
        """Allow to set the current camera node.
        Connected to signal 'currentNodeChanged()' emitted by camera node selector."""

        #  Remove previous observer
        if self.cameraNode and self.cameraNodeObserverTag:
            self.cameraNode.RemoveObserver(self.cameraNodeObserverTag)
        if self.camera and self.cameraObserverTag:
            self.camera.RemoveObserver(self.cameraObserverTag)

        newCamera = None
        if newCameraNode:
            newCamera = newCameraNode.GetCamera()
            # Add CameraNode ModifiedEvent observer
            self.cameraNodeObserverTag = newCameraNode.AddObserver(vtk.vtkCommand.ModifiedEvent, self.onCameraNodeModified)
            # Add Camera ModifiedEvent observer
            self.cameraObserverTag = newCamera.AddObserver(vtk.vtkCommand.ModifiedEvent, self.onCameraNodeModified)

        self.cameraNode = newCameraNode
        self.camera = newCamera

        # Update UI
        self.updateWidgetFromMRML()

    def updateWidgetFromMRML(self):
        if self.camera:
            self.viewAngleSlider.value = self.camera.GetViewAngle()
        if self.cameraNode:
            pass

    def onCameraModified(self, observer, eventid):
        self.updateWidgetFromMRML()

    def onCameraNodeModified(self, observer, eventid):
        self.updateWidgetFromMRML()

    def enableOrDisableCreateButton(self):
        """Connected to both the fiducial and camera node selector. It allows to
        enable or disable the 'create path' button."""
        self.createPathButton.enabled = (self.cameraNodeSelector.currentNode() is not None
                                         and self.inputFiducialsNodeSelector.currentNode() is not None
                                         and self.outputPathNodeSelector.currentNode() is not None)

    def onCreatePathButtonClicked(self):
        """Connected to 'create path' button. It allows to:
          - compute the path
          - create the associated model"""

        fiducialsNode = self.inputFiducialsNodeSelector.currentNode()
        outputPathNode = self.outputPathNodeSelector.currentNode()
        print("Calculating Path...")
        result = EndoscopyComputePath(fiducialsNode)
        print("-> Computed path contains %d elements" % len(result.path))

        print("Create Model...")
        model = EndoscopyPathModel(result.path, fiducialsNode, outputPathNode)
        print("-> Model created")

        # Update frame slider range
        self.frameSlider.maximum = len(result.path) - 2

        # Update flythrough variables
        self.camera = self.camera
        self.transform = model.transform
        self.pathPlaneNormal = model.planeNormal
        self.path = result.path

        # Enable / Disable flythrough button
        self.flythroughCollapsibleButton.enabled = len(result.path) > 0

    def frameSliderValueChanged(self, newValue):
        # print "frameSliderValueChanged:", newValue
        self.flyTo(newValue)

    def frameSkipSliderValueChanged(self, newValue):
        # print "frameSkipSliderValueChanged:", newValue
        self.skip = int(newValue)

    def frameDelaySliderValueChanged(self, newValue):
        # print "frameDelaySliderValueChanged:", newValue
        self.timer.interval = newValue

    def viewAngleSliderValueChanged(self, newValue):
        if not self.cameraNode:
            return
        # print "viewAngleSliderValueChanged:", newValue
        self.cameraNode.GetCamera().SetViewAngle(newValue)

    def onPlayButtonToggled(self, checked):
        if checked:
            self.timer.start()
            self.playButton.text = "Stop"
        else:
            self.timer.stop()
            self.playButton.text = "Play"

    def flyToNext(self):
        currentStep = self.frameSlider.value
        nextStep = currentStep + self.skip + 1
        if nextStep > len(self.path) - 2:
            nextStep = 0
        self.frameSlider.value = nextStep

    def flyTo(self, pathPointIndex):
        if not hasattr(self, "resampledCurve"):
            return

        cameraPosition = np.zeros((3,))
        self.resampledCurve.GetNthControlPointPositionWorld(pathPointIndex, cameraPosition)
        focalPointPosition = np.zeros((3,))
        self.resampledCurve.GetNthControlPointPositionWorld(pathPointIndex + 1, focalPointPosition)

        defaultOrientation = self.GetDefaultOrientation(pathPointIndex)
        relativeOrientation = np.zeros((4,))
        self.resampledCurve.GetNthControlPointOrientation(pathPointIndex, relativeOrientation)
        resultMatrix = np.matmul(
            EndoscopyPathModel.OrientationToMatrix3x3(relativeOrientation),
            EndoscopyPathModel.OrientationToMatrix3x3(defaultOrientation),
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


class EndoscopyComputePath:
    """Compute path given a list of fiducials.
    Path is stored in 'path' member variable as a numpy array.
    If a point list is received then curve points are generated using Hermite spline interpolation.
    See https://en.wikipedia.org/wiki/Cubic_Hermite_spline

    Example:
      result = EndoscopyComputePath(fiducialListNode)
      print "computer path has %d elements" % len(result.path)

    """

    def __init__(self, fiducialListNode, dl=0.5):
        self.dl = dl  # desired world space step size (in mm)

        if not (
            self.SetCurveFromInput(fiducialListNode)
            and self.SetCameraPositionsFromInputCurve()
            and self.SetCameraOrientationsFromInputCurve()
        ):
            self.IndicateFailure()
            return

    def SetCurveFromInput(self, fiducialListNode):
        # Make a deep copy of the input information as a vtkMRMLMarkupsCurveNode.
        self.inputCurve = slicer.vtkMRMLMarkupsCurveNode()
        if (
            fiducialListNode.GetClassName() == "vtkMRMLMarkupsFiducialNode"
            or fiducialListNode.GetClassName() == "vtkMRMLMarkupsCurveNode"
            or fiducialListNode.GetClassName() == "vtkMRMLMarkupsClosedCurveNode"
        ):
            n = fiducialListNode.GetNumberOfControlPoints()
            if n < 2:
                # Need at least two points to make segments.
                slicer.util.errorDisplay(
                    "You need at least 2 control points in order to make a fly through.", "Run Error"
                )
                return False
            coord = np.zeros((3,))
            for i in range(n):
                fiducialListNode.GetNthControlPointPositionWorld(i, coord)
                self.inputCurve.AddControlPointWorld(*coord)

            # Copy all the orientation information to the new curve.
            if (
                fiducialListNode.GetClassName() == "vtkMRMLMarkupsCurveNode"
                or fiducialListNode.GetClassName() == "vtkMRMLMarkupsClosedCurveNode"
            ):
                # TODO: How do we distinguish a user-supplied identity matrix from a user's request that the orientation
                # for this position be computed via interpolation?  For the moment we assume that the user has supplied
                # an orientation for every control point.
                orientation = np.zeros((4,))
                for i in range(n):
                    fiducialListNode.GetNthControlPointOrientation(i, orientation)
                    self.inputCurve.SetNthControlPointOrientation(i, *orientation)
            else:
                # TODO: No orientation information is available.  For the moment assume that the user effectively
                # supplied the identity matrix for each control point.
                orientation = np.array([0.0, 0.0, 0.0, 1.0])
                for i in range(n):
                    self.inputCurve.SetNthControlPointOrientation(i, *orientation)
        else:
            # Unrecognized type for fiducialListNode
            slicer.util.errorDisplay(
                "The fiducialListNode must be a vtkMRMLMarkupsFiducialNode, vtkMRMLMarkupsCurveNode, or"
                + " vtkMRMLMarkupsClosedCurveNode.  {fiducialListNode.GetClassName()} cannot be processed.",
                "Run Error",
            )
            return False
        return True

    def SetCameraPositionsFromInputCurve(self):
        # We now have the user's input as a curve.  Let's get equidistant points to represent the curve.
        resampledPoints = vtk.vtkPoints()
        slicer.vtkMRMLMarkupsCurveNode.ResamplePoints(
            self.inputCurve.GetCurvePointsWorld(), resampledPoints, self.dl, self.inputCurve.GetCurveClosed()
        )
        self.n = resampledPoints.GetNumberOfPoints()
        if self.n < 2:
            slicer.util.errorDisplay(
                "The curve is of length {self.inputCurve.GetCurveLengthWorld()}"
                + " and is too short to support a step size of {self.dl}.",
                "Run Error",
            )
            return False

        # Make a curve from these resampledPoints
        self.resampledCurve = slicer.vtkMRMLMarkupsCurveNode()
        coord = np.zeros((3,))
        for i in range(self.n):
            resampledPoints.GetPoint(i, coord)
            self.resampledCurve.AddControlPointWorld(*coord)

        # TODO: What else for self.resampledCurve should be set?

        return True

    def SetCameraOrientationsFromInputCurve():
        # Interpolate the camera orientations for our resampledPoints

        # Find the camera orientations in the input curve
        n = self.inputCurve.GetNumberOfControlPoints()
        quaternionInterpolator = vtk.vtkQuaternionInterpolator()
        quaternionInterpolator.SetSearchMethod(0)  # binary search
        quaternionInterpolator.SetInterpolationTypeToSpline()  # cubic rather than linear interpolation
        for i in range(n):
            # TODO: For the moment assume that all orientations have been supplied by the user.  This loop should
            # instead include only user-supplied interpolations.  Those that are not supplied by the user, and thus are
            # in need of being computed via interpolation, should not be supplied via .AddQuaternion().
            supplied = True
            if supplied or i == 0 or i == n - 1:
                distanceAlongInputCurve = self.inputCurve.GetCurveLengthWorld(0, i)
                orientation = np.array([0.0, 0.0, 0.0, 1.0])
                if supplied:
                    self.GetRelativeOrientation(i, orientation)
                quaternion = EndoscopyComputePath.OrientationToQuaternion(orientation)
                quaternionInterpolator.AddQuaternion(distanceAlongInputCurve, *quaternion)

        # Find the places at which we wish to have orientations
        for i in range(self.n):
            distanceAlongResampledCurve = self.resampledCurve.GetCurveLengthWorld(0, i)
            quaternion = np.zeros((4,))
            quaternionInterpolator.InterpolateQuaternion(distanceAlongResampledCurve, quaternion)
            orientation = EndoscopyComputePath.QuaternionToOrientation(quaternion)
            self.resampledCurve.SetNthControlPointOrientation(i, *orientation)

    def GetDefaultOrientation(self, i, orientation=None):
        cameraPosition = np.zeros((3,))
        self.resampledCurve.GetNthControlPointPositionWorld(i, cameraPosition)
        focalPointPosition = np.zeros((3,))
        self.resampledCurve.GetNthControlPointPositionWorld(i + 1, focalPointPosition)
        matrix3x3 = np.zeros((3, 3))
        matrix3x3[:, 2] = focalPointPosition - cameraPosition
        matrix3x3[:, 2] /= np.linalg.norm(matrix3x3[:, 2])
        matrix3x3[:, 0] = np.cross(self.pathPlaneNormal, matrix3x3[:, 2])
        matrix3x3[:, 0] /= np.linalg.norm(matrix3x3[:, 0])
        matrix3x3[:, 1] = np.cross(matrix3x3[:, 2], matrix3x3[:, 0])
        return EndoscopyComputePath.Matrix3x3ToOrientation(matrix3x3, orientation)

    def GetRelativeOrientation(self, i, resultOrientation=None):
        rightOrientation = self.GetDefaultOrientation(i)
        # Compute the inverse of rightOrientation by negating its angle of rotation.
        rightOrientation[0] *= -1.0

        leftOrientation = np.zeros((4,))
        self.inputCurve.GetNthControlPointOrientation(i, leftOrientation)

        return EndoscopyComputePath.MultiplyOrientations(leftOrientation, rightOrientation, resultOrientation)

    def IndicateFailure(self):
        # We cannot fly through if there is no self.resampledCurve.
        if hasattr(self, "resampledCurve"):
            del self.resampledCurve

    @staticmethod
    def Matrix3x3ToOrientation(matrix3x3, orientation=np.zeros((4,))):
        vtkQ = vtk.vtkQuaternion[np.float64]()
        vtkQ.FromMatrix(matrix3x3)
        vtkQ.GetRotationAngleAndAxis(orientation)
        return orientation

    @staticmethod
    def Matrix3x3ToQuaternion(matrix3x3, quaternion=np.zeros((4,))):
        vtkQ = vtk.vtkQuaternion[np.float64]()
        vtkQ.FromMatrix(matrix3x3)
        vtkQ.Get(quaternion)
        return quaternion

    @staticmethod
    def OrientationToMatrix3x3(orientation, matrix3x3=np.zeros((3, 3))):
        vtkQ = vtk.vtkQuaternion[np.float64]()
        vtkQ.SetRotationAngleAndAxis(*orientation)
        vtkQ.ToMatrix(matrix3x3)
        return matrix3x3

    @staticmethod
    def OrientationToQuaternion(orientation, quaternion=np.zeros((4,))):
        vtkQ = vtk.vtkQuaternion[np.float64]()
        vtkQ.SetRotationAngleAndAxis(*orientation)
        vtkQ.Get(quaternion)
        return quaternion

    @staticmethod
    def QuaternionToMatrix3x3(quaternion, matrix3x3=np.zeros((3, 3))):
        vtkQ = vtk.vtkQuaternion[np.float64]()
        vtkQ.Set(*quaternion)
        vtkQ.ToMatrix(matrix3x3)
        return matrix3x3

    @staticmethod
    def QuaternionToOrientation(quaternion, orientation=np.zeros((4,))):
        vtkQ = vtk.vtkQuaternion[np.float64]()
        vtkQ.Set(*quaternion)
        vtkQ.GetRotationAngleAndAxis(orientation)
        return orientation

    @staticmethod
    def MultiplyOrientations(leftOrientation, rightOrientation, resultOrientation=None):
        return EndoscopyComputePath.Matrix3x3ToOrientation(
            np.matmul(
                EndoscopyComputePath.OrientationToMatrix3x3(leftOrientation),
                EndoscopyComputePath.OrientationToMatrix3x3(rightOrientation),
            ),
            resultOrientation,
        )


class EndoscopyPathModel:
    """Create a vtkPolyData for a polyline:
         - Add one point per path point.
         - Add a single polyline
    """

    def __init__(self, path, fiducialListNode, outputPathNode=None, cursorType=None):
        """
          :param path: path points as numpy array.
          :param fiducialListNode: input node, just used for naming the output node.
          :param outputPathNode: output model node that stores the path points.
          :param cursorType: can be 'markups' or 'model'. Markups has a number of advantages (radius it is easier to change the size,
            can jump to views by clicking on it, has more visualization options, can be scaled to fixed display size),
            but if some applications relied on having a model node as cursor then this argument can be used to achieve that.
        """

        fids = fiducialListNode
        scene = slicer.mrmlScene

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

        for point in path:
            pointIndex = points.InsertNextPoint(*point)
            linesIDArray.InsertNextTuple1(pointIndex)
            linesIDArray.SetTuple1(0, linesIDArray.GetNumberOfTuples() - 1)
            lines.SetNumberOfCells(1)

        pointsArray = vtk.util.numpy_support.vtk_to_numpy(points.GetData())
        self.planePosition, self.planeNormal = self.planeFit(pointsArray.T)

        # Create model node
        model = outputPathNode
        if not model:
            model = scene.AddNewNodeByClass("vtkMRMLModelNode", scene.GenerateUniqueName("Path-%s" % fids.GetName()))
            model.CreateDefaultDisplayNodes()
            model.GetDisplayNode().SetColor(1, 1, 0)  # yellow

        model.SetAndObservePolyData(polyData)

        # Camera cursor
        cursor = model.GetNodeReference("CameraCursor")
        if not cursor:

            if self.cursorType == "markups":
                # Markups cursor
                cursor = scene.AddNewNodeByClass("vtkMRMLMarkupsFiducialNode", scene.GenerateUniqueName("Cursor-%s" % fids.GetName()))
                cursor.CreateDefaultDisplayNodes()
                cursor.GetDisplayNode().SetSelectedColor(1, 0, 0)  # red
                cursor.GetDisplayNode().SetSliceProjection(True)
                cursor.AddControlPoint(vtk.vtkVector3d(0, 0, 0), " ")  # do not show any visible label
                cursor.SetNthControlPointLocked(0, True)
            else:
                # Model cursor
                cursor = scene.AddNewNodeByClass("vtkMRMLMarkupsModelNode", scene.GenerateUniqueName("Cursor-%s" % fids.GetName()))
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
            transform = scene.AddNewNodeByClass("vtkMRMLLinearTransformNode", scene.GenerateUniqueName("Transform-%s" % fids.GetName()))
            model.SetNodeReferenceID("CameraTransform", transform.GetID())
        cursor.SetAndObserveTransformNodeID(transform.GetID())

        self.transform = transform

    # source: https://stackoverflow.com/questions/12299540/plane-fitting-to-4-or-more-xyz-points
    def planeFit(self, points):
        """
        p, n = planeFit(points)

        Given an array, points, of shape (d,...)
        representing points in d-dimensional space,
        fit an d-dimensional plane to the points.
        Return a point, p, on the plane (the point-cloud centroid),
        and the normal, n.
        """

        from np.linalg import svd
        points = np.reshape(points, (np.shape(points)[0], -1))  # Collapse trialing dimensions
        assert points.shape[0] <= points.shape[1], f"There are only {points.shape[1]} points in {points.shape[0]} dimensions."
        ctr = points.mean(axis=1)
        x = points - ctr[:, np.newaxis]
        M = np.dot(x, x.T)  # Could also use np.cov(x) here.
        return ctr, svd(M)[0][:, -1]
