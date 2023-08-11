import ctk
import qt
import vtk
import vtk.util.numpy_support

import slicer
from slicer.ScriptedLoadableModule import *


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
        """ Apply the pathPointIndex-th step in the path to the global camera"""

        if self.path is None:
            return

        pathPointIndex = int(pathPointIndex)
        cameraPosition = self.path[pathPointIndex]
        wasModified = self.cameraNode.StartModify()

        self.camera.SetPosition(cameraPosition)
        focalPointPosition = self.path[pathPointIndex + 1]
        self.camera.SetFocalPoint(*focalPointPosition)
        self.camera.OrthogonalizeViewUp()

        toParent = vtk.vtkMatrix4x4()
        self.transform.GetMatrixTransformToParent(toParent)
        toParent.SetElement(0, 3, cameraPosition[0])
        toParent.SetElement(1, 3, cameraPosition[1])
        toParent.SetElement(2, 3, cameraPosition[2])

        # Set up transform orientation component so that
        # Z axis is aligned with view direction and
        # Y vector is aligned with the curve's plane normal.
        # This can be used for example to show a reformatted slice
        # using with SlicerIGT extension's VolumeResliceDriver module.
        import numpy as np
        # TODO: Split this next statement into two so that we compute focalPointPosition-cameraPosition only once.
        zVec = (focalPointPosition - cameraPosition) / np.linalg.norm(focalPointPosition - cameraPosition)
        # TODO: This isn't yVec.  Eliminate this next statement and use self.pathPlaneNormal in the following statement.
        yVec = self.pathPlaneNormal
        xVec = np.cross(yVec, zVec)
        xVec /= np.linalg.norm(xVec)
        yVec = np.cross(zVec, xVec)
        toParent.SetElement(0, 0, xVec[0])
        toParent.SetElement(1, 0, xVec[1])
        toParent.SetElement(2, 0, xVec[2])
        toParent.SetElement(0, 1, yVec[0])
        toParent.SetElement(1, 1, yVec[1])
        toParent.SetElement(2, 1, yVec[2])
        toParent.SetElement(0, 2, zVec[0])
        toParent.SetElement(1, 2, zVec[1])
        toParent.SetElement(2, 2, zVec[2])

        # TODO: Via simple matrix4x4 multiplication (cameraTransform * toParent), apply the
        # self.pathCameraTransform[pathPointIndex] transform to move the camera (translation and/or orientation)
        # according to the user's specification.  The user specifies (directly or via interpolation) the transformation
        # relative to the default Endoscopy orientation just calculated.

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
        import numpy
        self.dl = dl  # desired world space step size (in mm)
        self.dt = dl  # current guess of parametric stepsize
        self.fids = fiducialListNode

        # Already a curve, just get the points, sampled at equal distances.
        if (self.fids.GetClassName() == "vtkMRMLMarkupsCurveNode"
                or self.fids.GetClassName() == "vtkMRMLMarkupsClosedCurveNode"):
            # Temporarily increase the number of points per segment, to get a very smooth curve
            pointsPerSegment = int(self.fids.GetCurveLengthWorld() / self.dl / self.fids.GetNumberOfControlPoints()) + 1
            originalPointsPerSegment = self.fids.GetNumberOfPointsPerInterpolatingSegment()
            if originalPointsPerSegment < pointsPerSegment:
                self.fids.SetNumberOfPointsPerInterpolatingSegment(pointsPerSegment)
            # Get equidistant points
            resampledPoints = vtk.vtkPoints()
            slicer.vtkMRMLMarkupsCurveNode.ResamplePoints(self.fids.GetCurvePointsWorld(), resampledPoints, self.dl, self.fids.GetCurveClosed())
            # Restore original number of pointsPerSegment
            if originalPointsPerSegment < pointsPerSegment:
                self.fids.SetNumberOfPointsPerInterpolatingSegment(originalPointsPerSegment)
            # Get it as a numpy array as an independent copy
            self.path = vtk.util.numpy_support.vtk_to_numpy(resampledPoints.GetData())
            # TODO: We are able to set self.pathIndices when we process vtkMRMLMarkupsFiducialNode below. How do we set
            # it in the present case for vtkMRMLMarkupsCurveNode and vtkMRMLMarkupsClosedCurveNode?
            return

        # hermite interpolation functions
        # TODO: flake8 would complain that it is better to use `@staticmethod def` than to name a lambda in this way.
        self.h00 = lambda t: 2 * t**3 - 3 * t**2 + 1
        self.h10 = lambda t: t**3 - 2 * t**2 + t
        self.h01 = lambda t: -2 * t**3 + 3 * t**2
        self.h11 = lambda t: t**3 - t**2

        # n is the number of control points in the piecewise curve

        if self.fids.GetClassName() == "vtkMRMLMarkupsFiducialNode":
            # slicer4 Markups node
            self.n = self.fids.GetNumberOfControlPoints()
            n = self.n
            if n == 0:
                return
            # get fiducial positions
            # sets self.p
            self.p = numpy.zeros((n, 3))
            for i in range(n):
                coord = [0.0, 0.0, 0.0]
                # TODO: Simply use self.p[i] directly in the next statement, avoiding coord.
                self.fids.GetNthControlPointPositionWorld(i, coord)
                self.p[i] = coord

        # TODO: Eliminate creating the fm variable.  Instead do something direct like:
        # self.m[0] = p[1] - p[0]
        # self.m[1 : n - 1] = (p[2:n] - p[0 : n - 2]) / 2
        # self.m[n - 1] = p[n - 1] - p[n - 2]

        # calculate the tangent vectors
        # - fm is forward difference
        # - m is average of in and out vectors
        # - first tangent is out vector, last is in vector
        # - sets self.m
        n = self.n
        fm = numpy.zeros((n, 3))
        for i in range(0, n - 1):
            fm[i] = self.p[i + 1] - self.p[i]
        self.m = numpy.zeros((n, 3))
        for i in range(1, n - 1):
            self.m[i] = (fm[i - 1] + fm[i]) / 2.
        self.m[0] = fm[0]
        self.m[n - 1] = fm[n - 2]

        self.path = [self.p[0]]
        self.pathIndices = [(0, 0.0)]  # (segment, t)
        self.calculatePath()
        self.interpolateCameraTransforms()

    def calculatePath(self):
        """ Generate a flight path for of steps of length dl """
        #
        # calculate the actual path
        # - take steps of self.dl in world space
        # -- if dl steps into next segment, take a step of size "remainder" in the new segment
        # - put resulting points into self.path
        #
        n = self.n
        segment = 0  # which first point of current segment
        t = 0  # parametric current parametric increment
        remainder = 0  # how much of dl isn't included in current step
        # TODO: The following loop doesn't handle the case that a remainder may require advancing the segment index more
        # than once.  Instead: start with `self.path = []` rather than `self.path = [self.p[0]]` above. Then use
        # something like:

        # maxSegment = self.n - 2  # number of segments is one less than the number of points
        # while remainder == 0.0:
        #     self.path.append(p)
        #     self.pathIndices.append((segment, t))
        #     t, p, remainder = self.step(segment, t, self.dl)
        #     while remainder > 0.0 and segment < maxSegment:
        #         segment += 1
        #         t, p, remainder = self.step(segment, 0, remainder)

        while segment < n - 1:
            t, p, remainder = self.step(segment, t, self.dl)
            if remainder != 0 or t == 1.:
                segment += 1
                t = 0
                if segment < n - 1:
                    t, p, remainder = self.step(segment, t, remainder)
            self.path.append(p)
            self.pathIndices.append((segment, t))

    def point(self, segment, t):
        return (self.h00(t) * self.p[segment] +
                self.h10(t) * self.m[segment] +
                self.h01(t) * self.p[segment + 1] +
                self.h11(t) * self.m[segment + 1])

    def step(self, segment, t, dl):
        """ Take a step of dl and return the path point and new t
          return:
          t = new parametric coordinate after step
          p = point after step
          remainder = if step results in parametric coordinate > 1.0, then
            this is the amount of world space not covered by step
        """
        import numpy.linalg

        # TODO: This apparently works so that's an argument to not change it.  Nonetheless, a binary search would be
        # simpler, be guaranteed to terminate in 20 iterations (many fewer than 500), and be easier to "prove correct by
        # reading" than the current implementation:

        # pRecent = self.path[-1]  # most recent element in path
        # pLast = self.p[segment + 1]
        # dLast = numpy.linalg.norm(pLast - pRecent)
        # if dLast < dl:
        #     # When curvature is tight, it is possible that an intermediate point is more distant, but ignore that.
        #     response = (None, None, dl - dLast)
        # else:
        #     # Because dLast > dl we can do a binary search
        #     tLow = t
        #     tHigh = 1.0
        #     tMid = (tLow + tHigh) / 2.0
        #     pMid = self.point(segment, tMid)
        #     while tHigh - tLow > 1e-6:
        #         if numpy.linalg.norm(pMid - pRecent) < dl:
        #             tLow = tMid
        #         else:
        #             tHigh = tMid
        #         tMid = (tLow + tHigh) / 2.0
        #         pMid = self.point(segment, tMid)
        #     response = (tMid, pMid, 0.0)

        p0 = self.path[self.path.__len__() - 1]  # last element in path
        remainder = 0
        ratio = 100
        count = 0
        while abs(1. - ratio) > 0.05:
            t1 = t + self.dt
            pguess = self.point(segment, t1)
            dist = numpy.linalg.norm(pguess - p0)
            ratio = self.dl / dist
            self.dt *= ratio
            if self.dt < 0.00000001:
                return
            count += 1
            if count > 500:
                return (t1, pguess, 0)
        if t1 > 1.:
            t1 = 1.
            p1 = self.point(segment, t1)
            remainder = numpy.linalg.norm(p1 - pguess)
            pguess = p1
        return (t1, pguess, remainder)

    def interpolateCameraTransforms(self):
        # TODO: This approach works for the vtkMRMLMarkupsFiducialNode case.  We need to handle the
        # vtkMRMLMarkupsCurveNode / vtkMRMLMarkupsClosedCurveNode case too, which is more difficult because it doesn't
        # (yet) provide us self.pathIndices information.  Likely we will use Get/
        # SetNthControlPoint/GetNthControlPoint(), Get/ SetNthControlPointOrientationMatrix(), and/or Get/
        # SetNthControlPointOrientationMatrixWorld().

        # TODO: The new variable names self.pCameraTransform, self.pathCameraTransform, and self.pathIndices could
        # probably be clearer.

        # TODO: Likely each of the following steps should be its own subroutine.

        # TODO: Set `self.pCameraTransform` by getting the data from somewhere.  It is a list of (index, cameraTransform)
        # pairs, where index is the same index that makes self.p[index, :] the corresponding point in the self.p array.
        # (Note that index is not the position within the finer-grained self.path list.)  Not all index values need be
        # present.  Furthermore, if the first or last index value is missing, the associated cameraTransform will be
        # assumed to be no translation and no rotation with respect to the Endoscopy default camera position.  Other
        # missing values will be interpolated.
        pass

        # TODO: Convert all supplied self.pCameraTransform to be relative the default Endoscopy camera transform.
        pass

        # TODO: Prepend and append the identity transform if they are missing.
        pass

        # TODO: Interpolate transformations to fill in other missing 'index' values.  (Recall this is for the self.p
        # points, not the self.path points.)  In order to do interpolation, we have to decide on the appropriate
        # proportions.  We can assume that each segment is of equal length; e.g. the interpolation between the
        # cameraTransform for self.p[5] and the cameraTransform for self.p[7], to get the cameraTransform for self.p[6],
        # would assume that self.p[6] is halfway between self.p[5] and self.p[7].  Alternatively, we could use distances
        # such as numpy.linalg.norm(self.p[6]-self.p[5]) and numpy.linalg.norm(self.p[7]-self.p[6]).  Possibly, some
        # other approaches.
        pass

        # TODO: Set `self.pathCameraTransform`, which is the interpolation of the cameraTransforms associated with the
        # self.p points to get the cameraTransforms associated with the self.path points, using the self.pathIndices
        # information for the interpolation lengths.
        pass

    def ToQuaternion(xVec, yVec, zVec):
        """
        Converts system of axes to quaternion
        """
        matrix = vtk.vtkMatrix3x3()

        matrix.SetElement(0, 0, xVec[0])
        matrix.SetElement(1, 0, xVec[1])
        matrix.SetElement(2, 0, xVec[2])
        matrix.SetElement(0, 1, yVec[0])
        matrix.SetElement(1, 1, yVec[1])
        matrix.SetElement(2, 1, yVec[2])
        matrix.SetElement(0, 2, zVec[0])
        matrix.SetElement(1, 2, zVec[1])
        matrix.SetElement(2, 2, zVec[2])

        result = vtk.Quaternion()
        vtk.vtkMath.Matrix3x3ToQuaternion(matrix, result)
        return result


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
        import numpy as np
        from numpy.linalg import svd
        points = np.reshape(points, (np.shape(points)[0], -1))  # Collapse trialing dimensions
        assert points.shape[0] <= points.shape[1], f"There are only {points.shape[1]} points in {points.shape[0]} dimensions."
        ctr = points.mean(axis=1)
        x = points - ctr[:, np.newaxis]
        M = np.dot(x, x.T)  # Could also use np.cov(x) here.
        return ctr, svd(M)[0][:, -1]
