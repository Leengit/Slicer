/*=auto=========================================================================

  Portions (c) Copyright 2005 Brigham and Women's Hospital (BWH) All Rights Reserved.

  See COPYRIGHT.txt
  or http://www.slicer.org/copyright/copyright.txt for details.

  Program:   3D Slicer
  Module:    $RCSfile: vtkMRMLSliceLogic.cxx,v $
  Date:      $Date$
  Version:   $Revision$

=========================================================================auto=*/

// MRMLLogic includes
#include <vtkMRMLApplicationLogic.h>
#include <vtkMRMLSliceLayerLogic.h>
#include <vtkMRMLSliceLogic.h>

// MRML includes
#include <vtkMRMLAbstractVolumeResampler.h>
#include <vtkMRMLCrosshairNode.h>
#include <vtkMRMLGlyphableVolumeDisplayNode.h>
#include <vtkMRMLGlyphableVolumeSliceDisplayNode.h>
#include <vtkMRMLLinearTransformNode.h>
#include <vtkMRMLMarkupsCurveNode.h>
#include <vtkMRMLModelNode.h>
#include <vtkMRMLScalarVolumeDisplayNode.h>
#include <vtkMRMLScene.h>
#include <vtkMRMLSliceCompositeNode.h>
#include <vtkMRMLSliceDisplayNode.h>

// VTK includes
#include <vtkAlgorithmOutput.h>
#include <vtkAppendPolyData.h>
#include <vtkCollection.h>
#include <vtkCollectionIterator.h>
#include <vtkDoubleArray.h>
#include <vtkEventBroker.h>
#include <vtkGeneralTransform.h>
#include <vtkImageAppendComponents.h>
#include <vtkImageBlend.h>
#include <vtkImageCast.h>
#include <vtkImageData.h>
#include <vtkImageMathematics.h>
#include <vtkImageReslice.h>
#include <vtkMath.h>
#include <vtkNew.h>
#include <vtkOrientedGridTransform.h>
#include <vtkParallelTransportFrame.h>
#include <vtkPlane.h>
#include <vtkPlaneSource.h>
#include <vtkPointData.h>
#include <vtkPoints.h>
#include <vtkSmartPointer.h>
#include <vtkTransform.h>

// VTKAddon includes
#include <vtkAddonMathUtilities.h>

// STD includes
#include <algorithm>

//----------------------------------------------------------------------------
const int vtkMRMLSliceLogic::SLICE_INDEX_ROTATED=-1;
const int vtkMRMLSliceLogic::SLICE_INDEX_OUT_OF_VOLUME=-2;
const int vtkMRMLSliceLogic::SLICE_INDEX_NO_VOLUME=-3;
const std::string vtkMRMLSliceLogic::SLICE_MODEL_NODE_NAME_SUFFIX = std::string("Volume Slice");

//----------------------------------------------------------------------------
struct SliceLayerInfo
{
  SliceLayerInfo(vtkAlgorithmOutput* blendInput, double opacity)
  {
    this->BlendInput = blendInput;
    this->Opacity = opacity;
  }
  vtkSmartPointer<vtkAlgorithmOutput> BlendInput;
  double Opacity;
};

//----------------------------------------------------------------------------
struct BlendPipeline
{
  BlendPipeline()
  {
    /*
    // AlphaBlending, ReverseAlphaBlending:
    //
    //   foreground \
    //               > Blend
    //   background /
    //
    // Add, Subtract:
    //
    //   Casting is needed to avoid overflow during adding (or subtracting).
    //
    //   AddSubMath adds/subtracts alpha channel, therefore we copy RGB and alpha
    //   components and copy of the background's alpha channel to the output.
    //   Splitting and appending channels is probably quite inefficient, but there does not
    //   seem to be simpler pipeline to do this in VTK.
    //
    //   foreground > AddSubForegroundCast \
    //                                      > AddSubMath > AddSubOutputCast ...
    //   background > AddSubBackroundCast  /
    //
    //
    //     ... AddSubOutputCast > AddSubExtractRGB       \
    //
    //         background > AddSubExtractBackgroundAlpha - > AddSubAppendRGBA > Blend
    //
    //         foreground > AddSubExtractForegroundAlpha /
    //
    */

    this->AddSubForegroundCast->SetOutputScalarTypeToShort();
    this->AddSubBackgroundCast->SetOutputScalarTypeToShort();
    this->ForegroundFractionMath->SetConstantK(1.0);
    this->ForegroundFractionMath->SetOperationToMultiplyByK();
    this->ForegroundFractionMath->SetInputConnection(0, this->AddSubForegroundCast->GetOutputPort());
    this->AddSubMath->SetOperationToAdd();
    this->AddSubMath->SetInputConnection(0, this->AddSubBackgroundCast->GetOutputPort());
    this->AddSubMath->SetInputConnection(1, this->ForegroundFractionMath->GetOutputPort());
    this->AddSubOutputCast->SetInputConnection(this->AddSubMath->GetOutputPort());
    this->AddSubOutputCast->SetOutputScalarTypeToUnsignedChar();
    this->AddSubOutputCast->ClampOverflowOn();

    this->AddSubExtractRGB->SetInputConnection(this->AddSubOutputCast->GetOutputPort());
    this->AddSubExtractRGB->SetComponents(0, 1, 2);
    this->AddSubExtractBackgroundAlpha->SetComponents(3);
    this->AddSubExtractForegroundAlpha->SetComponents(3);

    this->BlendAlpha->AddInputConnection(this->AddSubExtractBackgroundAlpha->GetOutputPort());
    this->BlendAlpha->AddInputConnection(this->AddSubExtractForegroundAlpha->GetOutputPort());

    this->AddSubAppendRGBA->AddInputConnection(this->AddSubExtractRGB->GetOutputPort());
    this->AddSubAppendRGBA->AddInputConnection(this->BlendAlpha->GetOutputPort());
  }

  void AddLayers(std::deque<SliceLayerInfo>& layers,
    int sliceCompositing, bool clipToBackgroundVolume,
    vtkAlgorithmOutput* backgroundImagePort,
    vtkAlgorithmOutput* foregroundImagePort, double foregroundOpacity,
    vtkAlgorithmOutput* labelImagePort, double labelOpacity)
  {
    if (sliceCompositing == vtkMRMLSliceCompositeNode::Add || sliceCompositing == vtkMRMLSliceCompositeNode::Subtract)
    {
      if (!backgroundImagePort || !foregroundImagePort)
      {
        // not enough inputs for add/subtract, so use alpha blending pipeline
        sliceCompositing = vtkMRMLSliceCompositeNode::Alpha;
      }
    }

    if (sliceCompositing == vtkMRMLSliceCompositeNode::Alpha)
    {
      if (backgroundImagePort)
      {
        layers.emplace_back(backgroundImagePort, 1.0);
      }
      if (foregroundImagePort)
      {
        layers.emplace_back(foregroundImagePort, foregroundOpacity);
      }
    }
    else if (sliceCompositing == vtkMRMLSliceCompositeNode::ReverseAlpha)
    {
      if (foregroundImagePort)
      {
        layers.emplace_back(foregroundImagePort, 1.0);
      }
      if (backgroundImagePort)
      {
        layers.emplace_back(backgroundImagePort, foregroundOpacity);
      }
    }
    else
    {
      this->AddSubForegroundCast->SetInputConnection(foregroundImagePort);
      this->AddSubBackgroundCast->SetInputConnection(backgroundImagePort);
      this->AddSubExtractForegroundAlpha->SetInputConnection(foregroundImagePort);
      this->AddSubExtractBackgroundAlpha->SetInputConnection(backgroundImagePort);
      if (sliceCompositing == vtkMRMLSliceCompositeNode::Add)
      {
        this->AddSubMath->SetOperationToAdd();
      }
      else
      {
        this->AddSubMath->SetOperationToSubtract();
      }
      // If clip to background is disabled, blending occurs over the entire extent
      // of all layers, not just within the background volume region.
      if (!clipToBackgroundVolume)
      {
        this->BlendAlpha->SetOpacity(0, 0.5);
        this->BlendAlpha->SetOpacity(1, 0.5);
      }
      else
      {
        this->BlendAlpha->SetOpacity(0, 1.);
        this->BlendAlpha->SetOpacity(1, 0.);
      }

      layers.emplace_back(this->AddSubAppendRGBA->GetOutputPort(), 1.0);
    }

    // always blending the label layer
    if (labelImagePort)
    {
      layers.emplace_back(labelImagePort, labelOpacity);
    }
  }

  vtkNew<vtkImageCast> AddSubForegroundCast;
  vtkNew<vtkImageCast> AddSubBackgroundCast;
  vtkNew<vtkImageMathematics> AddSubMath;
  vtkNew<vtkImageMathematics> ForegroundFractionMath;
  vtkNew<vtkImageExtractComponents> AddSubExtractRGB;
  vtkNew<vtkImageExtractComponents> AddSubExtractBackgroundAlpha;
  vtkNew<vtkImageExtractComponents> AddSubExtractForegroundAlpha;
  vtkNew<vtkImageBlend> BlendAlpha;
  vtkNew<vtkImageAppendComponents> AddSubAppendRGBA;
  vtkNew<vtkImageCast> AddSubOutputCast;
  vtkNew<vtkImageBlend> Blend;
};

//----------------------------------------------------------------------------
vtkStandardNewMacro(vtkMRMLSliceLogic);

//----------------------------------------------------------------------------
vtkMRMLSliceLogic::vtkMRMLSliceLogic()
{
  this->BackgroundLayer = nullptr;
  this->ForegroundLayer = nullptr;
  this->LabelLayer = nullptr;
  this->SliceNode = nullptr;
  this->SliceCompositeNode = nullptr;

  this->Pipeline = new BlendPipeline;
  this->PipelineUVW = new BlendPipeline;

  this->ExtractModelTexture = vtkImageReslice::New();
  this->ExtractModelTexture->SetOutputDimensionality (2);
  this->ExtractModelTexture->SetInputConnection(this->PipelineUVW->Blend->GetOutputPort());

  this->SliceModelNode = nullptr;
  this->SliceModelTransformNode = nullptr;
  this->SliceModelDisplayNode = nullptr;
  this->ImageDataConnection = nullptr;
  this->SliceSpacing[0] = this->SliceSpacing[1] = this->SliceSpacing[2] = 1;
  this->AddingSliceModelNodes = false;

  this->CurvedPlanarReformationInit();
}

//----------------------------------------------------------------------------
vtkMRMLSliceLogic::~vtkMRMLSliceLogic()
{
  this->SetSliceNode(nullptr);

  if (this->ImageDataConnection)
  {
    this->ImageDataConnection = nullptr;
  }

  delete this->Pipeline;
  delete this->PipelineUVW;

  if (this->ExtractModelTexture)
  {
    this->ExtractModelTexture->Delete();
    this->ExtractModelTexture = nullptr;
  }

  this->SetBackgroundLayer (nullptr);
  this->SetForegroundLayer (nullptr);
  this->SetLabelLayer (nullptr);

  if (this->SliceCompositeNode)
  {
    vtkSetAndObserveMRMLNodeMacro( this->SliceCompositeNode, 0);
  }

  this->DeleteSliceModel();
}

//----------------------------------------------------------------------------
void vtkMRMLSliceLogic::SetMRMLSceneInternal(vtkMRMLScene * newScene)
{
  // List of events the slice logics should listen
  vtkNew<vtkIntArray> events;
  events->InsertNextValue(vtkMRMLScene::EndBatchProcessEvent);
  events->InsertNextValue(vtkMRMLScene::StartCloseEvent);
  events->InsertNextValue(vtkMRMLScene::EndImportEvent);
  events->InsertNextValue(vtkMRMLScene::EndRestoreEvent);
  events->InsertNextValue(vtkMRMLScene::NodeAddedEvent);
  events->InsertNextValue(vtkMRMLScene::NodeRemovedEvent);

  this->SetAndObserveMRMLSceneEventsInternal(newScene, events.GetPointer());

  this->ProcessMRMLLogicsEvents();

  this->BackgroundLayer->SetMRMLScene(newScene);
  this->ForegroundLayer->SetMRMLScene(newScene);
  this->LabelLayer->SetMRMLScene(newScene);

  this->ProcessMRMLSceneEvents(newScene, vtkMRMLScene::EndBatchProcessEvent, nullptr);
}

//----------------------------------------------------------------------------
void vtkMRMLSliceLogic::UpdateSliceNode()
{
  if (!this->GetMRMLScene())
  {
    this->SetSliceNode(nullptr);
  }

}

//----------------------------------------------------------------------------
void vtkMRMLSliceLogic::UpdateSliceNodeFromLayout()
{
  if (this->SliceNode == nullptr)
  {
    return;
  }
  this->SliceNode->SetOrientationToDefault();
}

//----------------------------------------------------------------------------
void vtkMRMLSliceLogic::UpdateSliceCompositeNode()
{
  if (!this->GetMRMLScene() || !this->SliceNode)
  {
    this->SetSliceCompositeNode(nullptr);
    return;
  }

  // find SliceCompositeNode in the scene
  std::string layoutName = (this->SliceNode->GetLayoutName() ? this->SliceNode->GetLayoutName() : "");
  vtkMRMLSliceCompositeNode* updatedSliceCompositeNode = vtkMRMLSliceLogic::GetSliceCompositeNode(this->GetMRMLScene(), layoutName.c_str());

  if (this->SliceCompositeNode && updatedSliceCompositeNode &&
       (!this->SliceCompositeNode->GetID() || strcmp(this->SliceCompositeNode->GetID(), updatedSliceCompositeNode->GetID()) != 0) )
  {
    // local SliceCompositeNode is out of sync with the scene
    this->SetSliceCompositeNode(nullptr);
  }

  if (!this->SliceCompositeNode)
  {
    if (!updatedSliceCompositeNode && !layoutName.empty())
    {
      // Use CreateNodeByClass instead of New to use default node specified in the scene
      updatedSliceCompositeNode = vtkMRMLSliceCompositeNode::SafeDownCast(this->GetMRMLScene()->CreateNodeByClass("vtkMRMLSliceCompositeNode"));
      updatedSliceCompositeNode->SetLayoutName(layoutName.c_str());
      this->GetMRMLScene()->AddNode(updatedSliceCompositeNode);
      this->SetSliceCompositeNode(updatedSliceCompositeNode);
      updatedSliceCompositeNode->Delete();
    }
    else
    {
      this->SetSliceCompositeNode(updatedSliceCompositeNode);
    }
  }
}

//----------------------------------------------------------------------------
bool vtkMRMLSliceLogic::EnterMRMLCallback()const
{
  return this->AddingSliceModelNodes == false;
}

//----------------------------------------------------------------------------
void vtkMRMLSliceLogic::UpdateFromMRMLScene()
{
  this->UpdateSliceNodes();
}

//----------------------------------------------------------------------------
void vtkMRMLSliceLogic::OnMRMLSceneNodeAdded(vtkMRMLNode* node)
{
  if (!(node->IsA("vtkMRMLSliceCompositeNode")
        || node->IsA("vtkMRMLSliceNode")
        || node->IsA("vtkMRMLVolumeNode")))
  {
    return;
  }
  this->UpdateSliceNodes();
}

//----------------------------------------------------------------------------
void vtkMRMLSliceLogic::OnMRMLSceneNodeRemoved(vtkMRMLNode* node)
{
  if (!(node->IsA("vtkMRMLSliceCompositeNode")
        || node->IsA("vtkMRMLSliceNode")
        || node->IsA("vtkMRMLVolumeNode")))
  {
    return;
  }
  this->UpdateSliceNodes();
}

//----------------------------------------------------------------------------
void vtkMRMLSliceLogic::OnMRMLSceneStartClose()
{
  this->UpdateSliceNodeFromLayout();
  this->DeleteSliceModel();
}

//----------------------------------------------------------------------------
void vtkMRMLSliceLogic::OnMRMLSceneEndImport()
{
  this->SetupCrosshairNode();
}

//----------------------------------------------------------------------------
void vtkMRMLSliceLogic::OnMRMLSceneEndRestore()
{
  this->SetupCrosshairNode();
}

//----------------------------------------------------------------------------
void vtkMRMLSliceLogic::UpdateSliceNodes()
{
  if (this->GetMRMLScene()
      && this->GetMRMLScene()->IsBatchProcessing())
  {
    return;
  }
  // Set up the nodes
  this->UpdateSliceNode();
  this->UpdateSliceCompositeNode();

  // Set up the models
  this->CreateSliceModel();

  this->UpdatePipeline();
}

//----------------------------------------------------------------------------
void vtkMRMLSliceLogic::SetupCrosshairNode()
{
  //
  // On a new scene or restore, create the singleton for the default crosshair
  // for navigation or cursor if it doesn't already exist in scene
  //
  bool foundDefault = false;
  vtkMRMLNode* node;
  vtkCollectionSimpleIterator it;
  vtkSmartPointer<vtkCollection> crosshairs = vtkSmartPointer<vtkCollection>::Take(this->GetMRMLScene()->GetNodesByClass("vtkMRMLCrosshairNode"));
  for (crosshairs->InitTraversal(it);
       (node = (vtkMRMLNode*)crosshairs->GetNextItemAsObject(it)) ;)
  {
    vtkMRMLCrosshairNode* crosshairNode =
      vtkMRMLCrosshairNode::SafeDownCast(node);
    if (crosshairNode
        && crosshairNode->GetCrosshairName() == std::string("default"))
    {
      foundDefault = true;
      break;
    }
  }

  if (!foundDefault)
  {
    vtkNew<vtkMRMLCrosshairNode> crosshair;
    this->GetMRMLScene()->AddNode(crosshair.GetPointer());
  }
}

//----------------------------------------------------------------------------
void vtkMRMLSliceLogic::OnMRMLNodeModified(vtkMRMLNode* node)
{
  assert(node);
  if (this->GetMRMLScene()->IsBatchProcessing())
  {
    return;
  }

  /// set slice extents in the layes
  this->SetSliceExtentsToSliceNode();

  // Update from SliceNode
  if (node == this->SliceNode)
  {
    // assert (sliceNode == this->SliceNode); not an assert because the node
    // might have change in CreateSliceModel() or UpdateSliceNode()
    vtkMRMLDisplayNode* sliceDisplayNode =
      this->SliceModelNode ? this->SliceModelNode->GetModelDisplayNode() : nullptr;
    if ( sliceDisplayNode)
    {
      sliceDisplayNode->SetVisibility( this->SliceNode->GetSliceVisible() );
      sliceDisplayNode->SetViewNodeIDs( this->SliceNode->GetThreeDViewIDs());
    }

    vtkMRMLSliceLogic::UpdateReconstructionSlab(this, this->GetBackgroundLayer());
    vtkMRMLSliceLogic::UpdateReconstructionSlab(this, this->GetForegroundLayer());

    // TODO: Update helper for curved planar reformation

  }
  else if (node == this->SliceCompositeNode)
  {
    this->UpdatePipeline();
    this->InvokeEvent(CompositeModifiedEvent);
  }
}

//----------------------------------------------------------------------------
void vtkMRMLSliceLogic
::ProcessMRMLLogicsEvents(vtkObject* vtkNotUsed(caller),
                          unsigned long vtkNotUsed(event),
                          void* vtkNotUsed(callData))
{
  this->ProcessMRMLLogicsEvents();
}

//----------------------------------------------------------------------------
void vtkMRMLSliceLogic::ProcessMRMLLogicsEvents()
{
  // Slice update may trigger redrawing many nodes, pause the render to
  // not spend time with intermediate renderings
  vtkMRMLApplicationLogic* appLogic = this->GetMRMLApplicationLogic();
  if (appLogic)
  {
    appLogic->PauseRender();
  }

  //
  // if we don't have layers yet, create them
  //
  if ( this->BackgroundLayer == nullptr )
  {
    vtkNew<vtkMRMLSliceLayerLogic> layer;
    this->SetBackgroundLayer(layer.GetPointer());
  }
  if ( this->ForegroundLayer == nullptr )
  {
    vtkNew<vtkMRMLSliceLayerLogic> layer;
    this->SetForegroundLayer(layer.GetPointer());
  }
  if ( this->LabelLayer == nullptr )
  {
    vtkNew<vtkMRMLSliceLayerLogic> layer;
    // turn on using the label outline only in this layer
    layer->IsLabelLayerOn();
    this->SetLabelLayer(layer.GetPointer());
  }
  // Update slice plane geometry
  if (this->SliceNode != nullptr
      && this->GetSliceModelNode() != nullptr
      && this->GetMRMLScene() != nullptr
      && this->GetMRMLScene()->GetNodeByID( this->SliceModelNode->GetID() ) != nullptr
      && this->SliceModelNode->GetPolyData() != nullptr )
  {
    int *dims1=nullptr;
    int dims[3];
    vtkSmartPointer<vtkMatrix4x4> textureToRAS;
    // If the slice resolution mode is not set to match the 2D view, use UVW dimensions
    if (this->SliceNode->GetSliceResolutionMode() != vtkMRMLSliceNode::SliceResolutionMatch2DView)
    {
      textureToRAS = this->SliceNode->GetUVWToRAS();
      dims1 = this->SliceNode->GetUVWDimensions();
      dims[0] = dims1[0]-1;
      dims[1] = dims1[1]-1;
    }
    else // If the slice resolution mode is set to match the 2D view, use texture computed by slice view
    {
      // Create a new textureToRAS matrix with translation to correct texture pixel origin
      //
      // Since the OpenGL texture pixel origin is in the pixel corner and the
      // VTK pixel origin is in the pixel center, we need to shift the coordinate
      // by half voxel.
      //
      // Considering that the translation matrix is almost an identity matrix, the
      // computation easily and efficiently performed by elementary operations on
      // the matrix elements.
      textureToRAS = vtkSmartPointer<vtkMatrix4x4>::New();
      textureToRAS->DeepCopy(this->SliceNode->GetXYToRAS());
      textureToRAS->SetElement(0, 3, textureToRAS->GetElement(0, 3)
        - 0.5 * textureToRAS->GetElement(0, 0) - 0.5 * textureToRAS->GetElement(0, 1)); // Shift by half voxel
      textureToRAS->SetElement(1, 3, textureToRAS->GetElement(1, 3)
        - 0.5 * textureToRAS->GetElement(1, 0) - 0.5 * textureToRAS->GetElement(1, 1)); // Shift by half voxel

      // Use XY dimensions for slice node if resolution mode is set to match 2D view
      dims1 = this->SliceNode->GetDimensions();
      dims[0] = dims1[0];
      dims[1] = dims1[1];
    }

    // Force non-zero dimension to avoid "Bad plane coordinate system"
    // error from vtkPlaneSource when slice viewers have a height or width
    // of zero.
    dims[0] = std::max(1, dims[0]);
    dims[1] = std::max(1, dims[1]);

    // set the plane corner point for use in a model
    double inPoint[4]={0,0,0,1};
    double outPoint[4];
    double *outPoint3 = outPoint;

    // set the z position to be the active slice (from the lightbox)
    inPoint[2] = this->SliceNode->GetActiveSlice();

    vtkPlaneSource* plane = vtkPlaneSource::SafeDownCast(
      this->SliceModelNode->GetPolyDataConnection()->GetProducer());

    int wasModified = this->SliceModelNode->StartModify();

    textureToRAS->MultiplyPoint(inPoint, outPoint);
    plane->SetOrigin(outPoint3);

    inPoint[0] = dims[0];
    textureToRAS->MultiplyPoint(inPoint, outPoint);
    plane->SetPoint1(outPoint3);

    inPoint[0] = 0;
    inPoint[1] = dims[1];
    textureToRAS->MultiplyPoint(inPoint, outPoint);
    plane->SetPoint2(outPoint3);

    this->SliceModelNode->EndModify(wasModified);

    this->UpdatePipeline();
    /// \tbd Ideally it should not be fired if the output polydata is not
    /// modified.
    plane->Modified();

    vtkMRMLModelDisplayNode *modelDisplayNode = this->SliceModelNode->GetModelDisplayNode();
    if ( modelDisplayNode )
    {
      if (this->LabelLayer && this->LabelLayer->GetImageDataConnectionUVW())
      {
        modelDisplayNode->SetInterpolateTexture(0);
      }
      else
      {
        modelDisplayNode->SetInterpolateTexture(1);
      }
    }
  }

  // This is called when a slice layer is modified, so pass it on
  // to anyone interested in changes to this sub-pipeline
  this->Modified();

  // All the updates are done, allow rendering again
  if (appLogic)
  {
    appLogic->ResumeRender();
  }
}

//----------------------------------------------------------------------------
vtkMRMLSliceNode* vtkMRMLSliceLogic::AddSliceNode(const char* layoutName)
{
  if (!this->GetMRMLScene())
  {
    vtkErrorMacro("vtkMRMLSliceLogic::AddSliceNode failed: scene is not set");
    return nullptr;
  }
  vtkSmartPointer<vtkMRMLSliceNode> node = vtkSmartPointer<vtkMRMLSliceNode>::Take(
    vtkMRMLSliceNode::SafeDownCast(this->GetMRMLScene()->CreateNodeByClass("vtkMRMLSliceNode")));
  node->SetName(layoutName);
  node->SetLayoutName(layoutName);
  this->GetMRMLScene()->AddNode(node);
  this->SetSliceNode(node);
  this->UpdateSliceNodeFromLayout();
  return node;
}

//----------------------------------------------------------------------------
void vtkMRMLSliceLogic::SetSliceNode(vtkMRMLSliceNode * newSliceNode)
{
  if (this->SliceNode == newSliceNode)
  {
    return;
  }

  // Observe the slice node for general properties like slice visibility.
  // But the slice layers will also notify us when things like transforms have
  // changed.
  // This class takes care of passing the one slice node to each of the layers
  // so that users of this class only need to set the node one place.
  vtkSetAndObserveMRMLNodeMacro( this->SliceNode, newSliceNode );

  this->UpdateSliceCompositeNode();

  if (this->BackgroundLayer)
  {
    this->BackgroundLayer->SetSliceNode(newSliceNode);
  }
  if (this->ForegroundLayer)
  {
    this->ForegroundLayer->SetSliceNode(newSliceNode);
  }
  if (this->LabelLayer)
  {
    this->LabelLayer->SetSliceNode(newSliceNode);
  }

  this->Modified();

}

//----------------------------------------------------------------------------
void vtkMRMLSliceLogic::SetSliceCompositeNode(vtkMRMLSliceCompositeNode *sliceCompositeNode)
{
  if (this->SliceCompositeNode == sliceCompositeNode)
  {
    return;
  }

  // Observe the composite node, since this holds the parameters for this pipeline
  vtkSetAndObserveMRMLNodeMacro( this->SliceCompositeNode, sliceCompositeNode );
  this->UpdatePipeline();
}

//----------------------------------------------------------------------------
void vtkMRMLSliceLogic::SetBackgroundLayer(vtkMRMLSliceLayerLogic *backgroundLayer)
{
  // TODO: Simplify the whole set using a macro similar to vtkMRMLSetAndObserve
  if (this->BackgroundLayer)
  {
    this->BackgroundLayer->SetMRMLScene( nullptr );
    this->BackgroundLayer->Delete();
  }
  this->BackgroundLayer = backgroundLayer;

  if (this->BackgroundLayer)
  {
    this->BackgroundLayer->Register(this);

    this->BackgroundLayer->SetMRMLScene(this->GetMRMLScene());

    this->BackgroundLayer->SetSliceNode(SliceNode);
    vtkEventBroker::GetInstance()->AddObservation(
      this->BackgroundLayer, vtkCommand::ModifiedEvent,
      this, this->GetMRMLLogicsCallbackCommand());
  }

  this->Modified();
}

//----------------------------------------------------------------------------
void vtkMRMLSliceLogic::SetForegroundLayer(vtkMRMLSliceLayerLogic *foregroundLayer)
{
  // TODO: Simplify the whole set using a macro similar to vtkMRMLSetAndObserve
  if (this->ForegroundLayer)
  {
    this->ForegroundLayer->SetMRMLScene( nullptr );
    this->ForegroundLayer->Delete();
  }
  this->ForegroundLayer = foregroundLayer;

  if (this->ForegroundLayer)
  {
    this->ForegroundLayer->Register(this);
    this->ForegroundLayer->SetMRMLScene( this->GetMRMLScene());

    this->ForegroundLayer->SetSliceNode(SliceNode);
    vtkEventBroker::GetInstance()->AddObservation(
      this->ForegroundLayer, vtkCommand::ModifiedEvent,
      this, this->GetMRMLLogicsCallbackCommand());
  }

  this->Modified();
}

//----------------------------------------------------------------------------
void vtkMRMLSliceLogic::SetLabelLayer(vtkMRMLSliceLayerLogic *labelLayer)
{
  // TODO: Simplify the whole set using a macro similar to vtkMRMLSetAndObserve
  if (this->LabelLayer)
  {
    this->LabelLayer->SetMRMLScene( nullptr );
    this->LabelLayer->Delete();
  }
  this->LabelLayer = labelLayer;

  if (this->LabelLayer)
  {
    this->LabelLayer->Register(this);

    this->LabelLayer->SetMRMLScene(this->GetMRMLScene());

    this->LabelLayer->SetSliceNode(SliceNode);
    vtkEventBroker::GetInstance()->AddObservation(
      this->LabelLayer, vtkCommand::ModifiedEvent,
      this, this->GetMRMLLogicsCallbackCommand());
  }

  this->Modified();
}

//----------------------------------------------------------------------------
void vtkMRMLSliceLogic
::SetWindowLevel(int layer, double newWindow, double newLevel)
{
  vtkMRMLScalarVolumeNode* volumeNode =
    vtkMRMLScalarVolumeNode::SafeDownCast( this->GetLayerVolumeNode (layer) );
  vtkMRMLScalarVolumeDisplayNode* volumeDisplayNode =
    volumeNode ? volumeNode->GetScalarVolumeDisplayNode() : nullptr;
  if (!volumeDisplayNode)
  {
    return;
  }
  int disabledModify = volumeDisplayNode->StartModify();
  volumeDisplayNode->SetAutoWindowLevel(0);
  volumeDisplayNode->SetWindowLevel(newWindow, newLevel);
  volumeDisplayNode->EndModify(disabledModify);
  this->Modified();
}

//----------------------------------------------------------------------------
void vtkMRMLSliceLogic
::GetWindowLevelAndRange(int layer, double& window, double& level,
  double& rangeLow, double& rangeHigh, bool& autoWindowLevel)
{
  vtkMRMLScalarVolumeNode* volumeNode =
    vtkMRMLScalarVolumeNode::SafeDownCast(this->GetLayerVolumeNode(layer));
  vtkMRMLScalarVolumeDisplayNode* volumeDisplayNode =
    volumeNode ? volumeNode->GetScalarVolumeDisplayNode() : nullptr;
  vtkImageData* imageData = (volumeDisplayNode && volumeNode) ? volumeNode->GetImageData() : nullptr;
  if (imageData)
    {
    window = volumeDisplayNode->GetWindow();
    level = volumeDisplayNode->GetLevel();
    double range[2] = {0.0, 255.0};
    imageData->GetScalarRange(range);
    rangeLow = range[0];
    rangeHigh = range[1];
    autoWindowLevel = (volumeDisplayNode->GetAutoWindowLevel() != 0);
    }
}

//----------------------------------------------------------------------------
void vtkMRMLSliceLogic
::SetBackgroundWindowLevel(double newWindow, double newLevel)
{
  // 0 is background layer, defined in this::GetLayerVolumeNode
  SetWindowLevel(vtkMRMLSliceLogic::LayerBackground, newWindow, newLevel);
}

//----------------------------------------------------------------------------
void vtkMRMLSliceLogic
::SetForegroundWindowLevel(double newWindow, double newLevel)
{
  // 1 is foreground layer, defined in this::GetLayerVolumeNode
  SetWindowLevel(vtkMRMLSliceLogic::LayerForeground, newWindow, newLevel);
}

//----------------------------------------------------------------------------
void vtkMRMLSliceLogic
::GetBackgroundWindowLevelAndRange(double& window, double& level,
                                         double& rangeLow, double& rangeHigh)
{
  bool autoWindowLevel; // unused, just a placeholder to allow calling the method
  this->GetBackgroundWindowLevelAndRange(window, level, rangeLow, rangeHigh, autoWindowLevel);
}

//----------------------------------------------------------------------------
void vtkMRMLSliceLogic
::GetBackgroundWindowLevelAndRange(double& window, double& level,
                                         double& rangeLow, double& rangeHigh, bool& autoWindowLevel)
{
  this->GetWindowLevelAndRange(vtkMRMLSliceLogic::LayerBackground, window, level, rangeLow, rangeHigh, autoWindowLevel);
}

//----------------------------------------------------------------------------
void vtkMRMLSliceLogic
::GetForegroundWindowLevelAndRange(double& window, double& level,
                                         double& rangeLow, double& rangeHigh)
{
  bool autoWindowLevel; // unused, just a placeholder to allow calling the method
  this->GetForegroundWindowLevelAndRange(window, level, rangeLow, rangeHigh, autoWindowLevel);
}

//----------------------------------------------------------------------------
void vtkMRMLSliceLogic
::GetForegroundWindowLevelAndRange(double& window, double& level,
                                         double& rangeLow, double& rangeHigh, bool& autoWindowLevel)
{
  this->GetWindowLevelAndRange(vtkMRMLSliceLogic::LayerForeground, window, level, rangeLow, rangeHigh, autoWindowLevel);
}

//----------------------------------------------------------------------------
vtkAlgorithmOutput * vtkMRMLSliceLogic::GetImageDataConnection()
{
  return this->ImageDataConnection;
}

//----------------------------------------------------------------------------
void vtkMRMLSliceLogic::UpdateImageData ()
{
  if (this->SliceNode->GetSliceResolutionMode() == vtkMRMLSliceNode::SliceResolutionMatch2DView)
  {
    this->ExtractModelTexture->SetInputConnection( this->Pipeline->Blend->GetOutputPort() );
    this->ImageDataConnection = this->Pipeline->Blend->GetOutputPort();
  }
  else
  {
    this->ExtractModelTexture->SetInputConnection( this->PipelineUVW->Blend->GetOutputPort() );
  }
  // It seems very strange that the imagedata can be null.
  // It should probably be always a valid imagedata with invalid bounds if needed

  if ( (this->GetBackgroundLayer() != nullptr && this->GetBackgroundLayer()->GetImageDataConnection() != nullptr) ||
       (this->GetForegroundLayer() != nullptr && this->GetForegroundLayer()->GetImageDataConnection() != nullptr) ||
       (this->GetLabelLayer() != nullptr && this->GetLabelLayer()->GetImageDataConnection() != nullptr) )
  {
    if (this->ImageDataConnection == nullptr || this->Pipeline->Blend->GetOutputPort()->GetMTime() > this->ImageDataConnection->GetMTime())
    {
      this->ImageDataConnection = this->Pipeline->Blend->GetOutputPort();
    }
  }
  else
  {
    this->ImageDataConnection = nullptr;
    if (this->SliceNode->GetSliceResolutionMode() == vtkMRMLSliceNode::SliceResolutionMatch2DView)
    {
      this->ExtractModelTexture->SetInputConnection( this->ImageDataConnection );
    }
    else
    {
      this->ExtractModelTexture->SetInputConnection(this->PipelineUVW->Blend->GetOutputPort());
    }
  }
}

//----------------------------------------------------------------------------
bool vtkMRMLSliceLogic::UpdateBlendLayers(vtkImageBlend* blend, const std::deque<SliceLayerInfo> &layers, bool clipToBackgroundVolume)
{
  const int blendPort = 0;
  vtkMTimeType oldBlendMTime = blend->GetMTime();

  bool layersChanged = false;
  int numberOfLayers = layers.size();
  if (numberOfLayers == blend->GetNumberOfInputConnections(blendPort))
  {
    int layerIndex = 0;
    for (std::deque<SliceLayerInfo>::const_iterator layerIt = layers.begin(); layerIt != layers.end(); ++layerIt, ++layerIndex)
    {
      if (layerIt->BlendInput != blend->GetInputConnection(blendPort, layerIndex))
      {
        layersChanged = true;
        break;
      }
    }
  }
  else
  {
    layersChanged = true;
  }
  if (layersChanged)
  {
    blend->RemoveAllInputs();
    int layerIndex = 0;
    for (std::deque<SliceLayerInfo>::const_iterator layerIt = layers.begin(); layerIt != layers.end(); ++layerIt, ++layerIndex)
    {
      blend->AddInputConnection(layerIt->BlendInput);
    }
  }

  // Update opacities
  {
    int layerIndex = 0;
    for (std::deque<SliceLayerInfo>::const_iterator layerIt = layers.begin(); layerIt != layers.end(); ++layerIt, ++layerIndex)
    {
      blend->SetOpacity(layerIndex, layerIt->Opacity);
    }
  }

  // Update blend mode: if clip to background is disabled, blending occurs over the entire extent
  // of all layers, not just within the background volume region.
  if (clipToBackgroundVolume)
  {
    blend->BlendAlphaOff();
  }
  else
  {
    blend->BlendAlphaOn();
  }

  bool modified = (blend->GetMTime() > oldBlendMTime);
  return modified;
}

//----------------------------------------------------------------------------
bool vtkMRMLSliceLogic::UpdateFractions(vtkImageMathematics* fraction, double opacity)
{
  vtkMTimeType oldMTime = fraction->GetMTime();
  fraction->SetConstantK(opacity);
  bool modified = (fraction->GetMTime() > oldMTime);
  return modified;
}

//----------------------------------------------------------------------------
void vtkMRMLSliceLogic::UpdateReconstructionSlab(vtkMRMLSliceLogic* sliceLogic, vtkMRMLSliceLayerLogic* sliceLayerLogic)
{
  if (!sliceLogic || !sliceLayerLogic || !sliceLogic->GetSliceNode() || !sliceLayerLogic->GetSliceNode())
  {
    return;
  }

  vtkImageReslice* reslice = sliceLayerLogic->GetReslice();
  vtkMRMLSliceNode* sliceNode = sliceLayerLogic->GetSliceNode();

  double sliceSpacing;
  if (sliceNode->GetSliceSpacingMode() == vtkMRMLSliceNode::PrescribedSliceSpacingMode)
  {
    sliceSpacing = sliceNode->GetPrescribedSliceSpacing()[2];
  }
  else
  {
    sliceSpacing = sliceLogic->GetLowestVolumeSliceSpacing()[2];
  }

  int slabNumberOfSlices = 1;
  if (sliceNode->GetSlabReconstructionEnabled()
      && sliceSpacing > 0
      && sliceNode->GetSlabReconstructionThickness() > sliceSpacing
      )
  {
    slabNumberOfSlices = static_cast<int>(sliceNode->GetSlabReconstructionThickness() / sliceSpacing);
  }
  reslice->SetSlabNumberOfSlices(slabNumberOfSlices);

  reslice->SetSlabMode(sliceNode->GetSlabReconstructionType());

  double slabSliceSpacingFraction = sliceSpacing / sliceNode->GetSlabReconstructionOversamplingFactor();
  reslice->SetSlabSliceSpacingFraction(slabSliceSpacingFraction);
}

//----------------------------------------------------------------------------
void
vtkMRMLSliceLogic::CurvedPlanarReformationInit()
{
  // there is no need to compute displacement for each slice, we just compute for every n-th to make computation faster
  // and inverse computation more robust (less contradiction because of there is less overlapping between neighbor
  // slices)
  this->CurvedPlanarReformationTransformSpacingFactor = 5.0;
}

//----------------------------------------------------------------------------
void
vtkMRMLSliceLogic::CurvedPlanarReformationGetPointsProjectedToPlane(vtkPoints *    pointsArrayIn,
                                                                    vtkMatrix4x4 * transformWorldToPlane,
                                                                    vtkPoints *    pointsArrayOut)
{
  // Returns points projected to the plane coordinate system (plane normal = plane Z axis).

  // Compute the inverse transformation
  vtkSmartPointer<vtkMatrix4x4> transformPlaneToWorld = vtkSmartPointer<vtkMatrix4x4>::New();
  vtkMatrix4x4::Invert(transformWorldToPlane, transformPlaneToWorld);

  const vtkIdType numPoints = pointsArrayIn->GetNumberOfPoints();
  double          pIn[4] = { 0.0, 0.0, 0.0, 1.0 };
  double          pMiddle[4] = { 0.0, 0.0, 0.0, 1.0 };
  double          pOut[4] = { 0.0, 0.0, 0.0, 1.0 };

  for (vtkIdType i = 0; i < numPoints; ++i)
  {
    // Note: uses only the first three elements of pIn
    pointsArrayIn->GetPoint(i, static_cast<double *>(pIn)); // requires double[3]
    // Point positions in the plane coordinate system:
    transformWorldToPlane->MultiplyPoint(pIn, pMiddle);
    // Projected point positions in the plane coordinate system:
    pMiddle[2] = 0.0;
    // Projected point positions in the world coordinate system:
    transformPlaneToWorld->MultiplyPoint(pMiddle, pOut);
    pointsArrayOut->SetPoint(i, pOut[0], pOut[1], pOut[2]);
  }
}

//----------------------------------------------------------------------------
bool
vtkMRMLSliceLogic::CurvedPlanarReformationComputeStraighteningTransform(
  vtkMRMLTransformNode *    transformToStraightenedNode,
  vtkMRMLMarkupsCurveNode * curveNode,
  const double              sliceSizeMm[2],
  double                    outputSpacingMm,
  bool                      stretching,
  double                    rotationDeg,
  vtkMRMLModelNode *        reslicingPlanesModelNode)
{
  /*
  Compute straightened volume (useful for example for visualization of curved vessels)
  stretching: if True then stretching transform will be computed, otherwise straightening
  */

  // Create a temporary resampled curve
  const double resamplingCurveSpacing = outputSpacingMm * this->CurvedPlanarReformationTransformSpacingFactor;
  vtkSmartPointer<vtkPoints> originalCurvePoints = curveNode->GetCurvePointsWorld();
  vtkSmartPointer<vtkPoints> sampledPoints = vtkSmartPointer<vtkPoints>::New();
  if (!vtkMRMLMarkupsCurveNode::ResamplePoints(originalCurvePoints, sampledPoints, resamplingCurveSpacing, false))
  {
    vtkErrorMacro("vtkMRMLSliceLogic::CurvedPlanarReformationComputeStraighteningTransform failed: "
                  "Resampling curve failed");
    return false;
  }
  vtkMRMLMarkupsCurveNode * resampledCurveNode = vtkMRMLMarkupsCurveNode::SafeDownCast(
    this->GetMRMLScene()->AddNewNodeByClass("vtkMRMLMarkupsCurveNode", "CurvedPlanarReformat_resampled_curve_temp"));
  resampledCurveNode->SetNumberOfPointsPerInterpolatingSegment(1);
  resampledCurveNode->SetCurveTypeToLinear();
  resampledCurveNode->SetControlPointPositionsWorld(sampledPoints);

  vtkPoints * resampledCurvePointsWorld = resampledCurveNode->GetCurvePointsWorld();
  if (resampledCurvePointsWorld == nullptr || resampledCurvePointsWorld->GetNumberOfPoints() < 3)
  {
    vtkErrorMacro("vtkMRMLSliceLogic::CurvedPlanarReformationComputeStraighteningTransform failed: "
                  "Not enough resampled curve points");
    return false;
  }
  vtkSmartPointer<vtkPlane> curveNodePlane = vtkSmartPointer<vtkPlane>::New();
  vtkAddonMathUtilities::FitPlaneToPoints(resampledCurvePointsWorld, curveNodePlane);

  // Z axis (from first curve point to last, this will be the straightened curve long axis)
  double curveStartPoint[3] = { 0.0, 0.0, 0.0 };
  double curveEndPoint[3] = { 0.0, 0.0, 0.0 };
  resampledCurveNode->GetNthControlPointPositionWorld(0, curveStartPoint);
  resampledCurveNode->GetNthControlPointPositionWorld(resampledCurveNode->GetNumberOfControlPoints() - 1,
                                                      curveEndPoint);
  double transformGridAxisZ[3];
  vtkMath::Subtract(curveEndPoint, curveStartPoint, transformGridAxisZ);
  vtkMath::Normalize(transformGridAxisZ);

  double transformGridAxisX[3];
  double transformGridAxisY[3];
  if (stretching)
  {
    // Y axis = best fit plane normal
    curveNodePlane->GetNormal(transformGridAxisY);

    // X axis normalize
    vtkMath::Cross(transformGridAxisZ, transformGridAxisY, transformGridAxisX);
    vtkMath::Normalize(transformGridAxisX);

    // Make sure that Z axis is orthogonal to X and Y
    double orthogonalizedTransformGridAxisZ[3];
    vtkMath::Cross(transformGridAxisX, transformGridAxisY, orthogonalizedTransformGridAxisZ);
    vtkMath::Normalize(orthogonalizedTransformGridAxisZ);
    if (vtkMath::Dot(transformGridAxisZ, orthogonalizedTransformGridAxisZ) > 0)
    {
      for (int i = 0; i < 3; ++i)
      {
        transformGridAxisZ[i] = orthogonalizedTransformGridAxisZ[1];
      }
    }
    else
    {
      for (int i = 0; i < 3; ++i)
      {
        transformGridAxisZ[i] = -orthogonalizedTransformGridAxisZ[i];
        transformGridAxisX[i] = -transformGridAxisX[i];
      }
    }
  }
  else
  {
    // X axis = average X axis of curve, to minimize torsion (and so have a
    // simple displacement field, which can be robustly inverted)
    double    sumCurveAxisX_RAS[3] = { 0.0, 0.0, 0.0 };
    const int numberOfPoints = resampledCurveNode->GetNumberOfControlPoints();
    for (int gridK = 0; gridK < numberOfPoints; ++gridK)
    {
      vtkSmartPointer<vtkMatrix4x4> curvePointToWorld = vtkSmartPointer<vtkMatrix4x4>::New();
      resampledCurveNode->GetCurvePointToWorldTransformAtPointIndex(
        resampledCurveNode->GetCurvePointIndexFromControlPointIndex(gridK), curvePointToWorld);
      const double curveAxisX_RAS[3] = { curvePointToWorld->GetElement(0, 0),
                                         curvePointToWorld->GetElement(1, 0),
                                         curvePointToWorld->GetElement(2, 0) };
      vtkMath::Add(sumCurveAxisX_RAS, curveAxisX_RAS, sumCurveAxisX_RAS);
    }
    vtkMath::Normalize(sumCurveAxisX_RAS);
    for (int i = 0; i < 3; ++i)
    {
      transformGridAxisX[i] = sumCurveAxisX_RAS[i];
    }

    // Y axis normalize
    vtkMath::Cross(transformGridAxisZ, transformGridAxisX, transformGridAxisY);
    vtkMath::Normalize(transformGridAxisY);

    // Make sure that X axis is orthogonal to Y and Z
    vtkMath::Cross(transformGridAxisY, transformGridAxisZ, transformGridAxisX);
    vtkMath::Normalize(transformGridAxisX);
  }

  // Rotate by rotationDeg around the Z axis
  vtkSmartPointer<vtkMatrix4x4> gridDirectionMatrix = vtkSmartPointer<vtkMatrix4x4>::New();
  gridDirectionMatrix->Identity();
  for (int i = 0; i < 3; ++i)
  {
    gridDirectionMatrix->SetElement(i, 0, transformGridAxisX[i]);
    gridDirectionMatrix->SetElement(i, 1, transformGridAxisY[i]);
    gridDirectionMatrix->SetElement(i, 2, transformGridAxisZ[i]);
  }
  //
  vtkSmartPointer<vtkTransform> gridDirectionTransform = vtkSmartPointer<vtkTransform>::New();
  gridDirectionTransform->Concatenate(gridDirectionMatrix);
  gridDirectionTransform->RotateZ(rotationDeg);
  //
  vtkSmartPointer<vtkMatrix4x4> rotatedGridMatrix = vtkSmartPointer<vtkMatrix4x4>::New();
  gridDirectionTransform->GetMatrix(rotatedGridMatrix);
  for (int i = 0; i < 3; ++i)
  {
    transformGridAxisX[i] = rotatedGridMatrix->GetElement(i, 0);
    transformGridAxisY[i] = rotatedGridMatrix->GetElement(i, 1);
    transformGridAxisZ[i] = rotatedGridMatrix->GetElement(i, 2);
  }

  if (stretching)
  {
    // Project curve points to grid YZ plane
    vtkSmartPointer<vtkMatrix4x4> transformFromGridYZPlane = vtkSmartPointer<vtkMatrix4x4>::New();
    transformFromGridYZPlane->Identity();
    const double * origin = curveNodePlane->GetOrigin();
    for (int i = 0; i < 3; ++i)
    {
      transformFromGridYZPlane->SetElement(i, 0, transformGridAxisY[i]);
      transformFromGridYZPlane->SetElement(i, 1, transformGridAxisZ[i]);
      transformFromGridYZPlane->SetElement(i, 2, transformGridAxisX[i]);
      transformFromGridYZPlane->SetElement(i, 3, origin[i]);
    }
    vtkSmartPointer<vtkMatrix4x4> transformToGridYZPlane = vtkSmartPointer<vtkMatrix4x4>::New();
    vtkMatrix4x4::Invert(transformFromGridYZPlane, transformToGridYZPlane);

    vtkPoints *                originalCurvePointsArray = curveNode->GetCurvePoints();
    vtkSmartPointer<vtkPoints> curvePointsProjected_RAS = vtkSmartPointer<vtkPoints>::New();
    this->CurvedPlanarReformationGetPointsProjectedToPlane(
      originalCurvePointsArray, transformToGridYZPlane, curvePointsProjected_RAS);
    for (int i = resampledCurveNode->GetNumberOfControlPoints() - 1; i >= 0; --i)
    {
      resampledCurveNode->RemoveNthControlPoint(i);
    }
    for (int i = 0; i < curvePointsProjected_RAS->GetNumberOfPoints(); ++i)
    {
      resampledCurveNode->AddControlPoint(curvePointsProjected_RAS->GetPoint(i));
    }

    // After projection, resampling is needed to get uniform distances
    originalCurvePoints = resampledCurveNode->GetCurvePointsWorld();
    sampledPoints->Reset();
    if (!vtkMRMLMarkupsCurveNode::ResamplePoints(originalCurvePoints, sampledPoints, resamplingCurveSpacing, false))
    {
      vtkErrorMacro("vtkMRMLSliceLogic::CurvedPlanarReformationComputeStraighteningTransform failed: "
                    "second call to resampling curve failed");
      return false;
    }
    for (int i = resampledCurveNode->GetNumberOfControlPoints() - 1; i >= 0; --i)
    {
      resampledCurveNode->RemoveNthControlPoint(i);
    }
    for (int i = 0; i < curvePointsProjected_RAS->GetNumberOfPoints(); ++i)
    {
      resampledCurveNode->AddControlPoint(sampledPoints->GetPoint(i));
    }
  }

  // Origin (makes the grid centered at the curve)
  const double   curveLength = resampledCurveNode->GetCurveLengthWorld();
  const double * origin = curveNodePlane->GetOrigin();
  double         transformGridOrigin[3] = { origin[0], origin[1], origin[2] };
  for (int i = 0; i < 3; ++i)
  {
    transformGridOrigin[i] -= transformGridAxisX[i] * sliceSizeMm[0] / 2.0;
    transformGridOrigin[i] -= transformGridAxisY[i] * sliceSizeMm[1] / 2.0;
    transformGridOrigin[i] -= transformGridAxisZ[i] * curveLength / 2.0;
  }

  // Create grid transform
  // Each corner of each slice is mapped from the original volume's reformatted slice
  // to the straightened volume slice.
  // The grid transform contains one vector at the corner of each slice.
  // The transform is in the same space and orientation as the straightened volume.
  const int                     numberOfSlices = resampledCurveNode->GetNumberOfControlPoints();
  const int                     gridDimensions[3] = { 2, 2, numberOfSlices };
  const double                  gridSpacing[3] = { sliceSizeMm[0], sliceSizeMm[1], resamplingCurveSpacing };
  vtkSmartPointer<vtkMatrix4x4> gridDirectionMatrixArray = vtkSmartPointer<vtkMatrix4x4>::New();
  gridDirectionMatrixArray->Identity();
  for (int i = 0; i < 3; ++i)
  {
    gridDirectionMatrixArray->SetElement(i, 0, transformGridAxisX[i]);
    gridDirectionMatrixArray->SetElement(i, 1, transformGridAxisY[i]);
    gridDirectionMatrixArray->SetElement(i, 2, transformGridAxisZ[i]);
  }

  vtkSmartPointer<vtkImageData> gridImage = vtkSmartPointer<vtkImageData>::New();
  gridImage->SetOrigin(transformGridOrigin);
  gridImage->SetDimensions(gridDimensions);
  gridImage->SetSpacing(gridSpacing);
  gridImage->AllocateScalars(VTK_DOUBLE, 3);
  vtkSmartPointer<vtkOrientedGridTransform> transform = vtkSmartPointer<vtkOrientedGridTransform>::New();
  transform->SetDisplacementGridData(gridImage);
  transform->SetGridDirectionMatrix(gridDirectionMatrixArray);
  transformToStraightenedNode->SetAndObserveTransformFromParent(transform);

  vtkSmartPointer<vtkAppendPolyData> appender = vtkSmartPointer<vtkAppendPolyData>::New();

  // Currently there is no API to set PreferredInitialNormalVector in the curve
  // coordinate system, therefore a new coordinate system generator must be set up:
  vtkSmartPointer<vtkParallelTransportFrame> curveCoordinateSystemGeneratorWorld =
    vtkSmartPointer<vtkParallelTransportFrame>::New();
  curveCoordinateSystemGeneratorWorld->SetInputData(resampledCurveNode->GetCurveWorld());
  curveCoordinateSystemGeneratorWorld->SetPreferredInitialNormalVector(transformGridAxisX);
  curveCoordinateSystemGeneratorWorld->Update();
  vtkPolyData *    curvePoly = curveCoordinateSystemGeneratorWorld->GetOutput();
  vtkPointData *   pointData = curvePoly->GetPointData();
  vtkDoubleArray * normals = vtkDoubleArray::SafeDownCast(
    pointData->GetAbstractArray(curveCoordinateSystemGeneratorWorld->GetNormalsArrayName()));
  vtkDoubleArray * binormals = vtkDoubleArray::SafeDownCast(
    pointData->GetAbstractArray(curveCoordinateSystemGeneratorWorld->GetBinormalsArrayName()));
  // vtkDoubleArray * tangents = vtkDoubleArray::SafeDownCast(
  //   pointData->GetAbstractArray(curveCoordinateSystemGeneratorWorld->GetTangentsArrayName()));

  // Compute displacements
  vtkSmartPointer<vtkDoubleArray> transformDisplacements_RAS = vtkSmartPointer<vtkDoubleArray>::New();
  transformDisplacements_RAS->SetNumberOfComponents(3);
  transformDisplacements_RAS->SetNumberOfTuples(gridDimensions[2] * gridDimensions[1] * gridDimensions[0]);
  for (int gridK = 0; gridK < gridDimensions[2]; ++gridK)
  {
    // The curve's built-in coordinate system generator could be used like this
    // (if it had PreferredInitialNormalVector exposed):
    //
    // curvePointToWorld = vtk.vtkMatrix4x4()
    // resampledCurveNode.GetCurvePointToWorldTransformAtPointIndex(
    //     resampledCurveNode.GetCurvePointIndexFromControlPointIndex(gridK),
    //     curvePointToWorld,
    // )
    // curvePointToWorldArray = slicer.util.arrayFromVTKMatrix(curvePointToWorld)
    // curveAxisX_RAS = curvePointToWorldArray[0:3, 0]
    // curveAxisY_RAS = curvePointToWorldArray[0:3, 1]
    // curvePoint_RAS = curvePointToWorldArray[0:3, 3]
    //
    // But now we get the values from our own coordinate system generator:
    const int      curvePointIndex = resampledCurveNode->GetCurvePointIndexFromControlPointIndex(gridK);
    const double * curveAxisX_RASVec = normals->GetTuple3(curvePointIndex);
    const double * curveAxisY_RASVec = binormals->GetTuple3(curvePointIndex);
    const double * curvePoint_RAS = curvePoly->GetPoint(curvePointIndex);

    vtkPlaneSource * plane = vtkPlaneSource::SafeDownCast(this->SliceModelNode->GetPolyDataConnection()->GetProducer());
    for (int gridJ = 0; gridJ < gridDimensions[1]; ++gridJ)
    {
      for (int gridI = 0; gridI < gridDimensions[0]; ++gridI)
      {
        double straightenedVolume_RAS[3];
        double inputVolume_RAS[3];
        for (int i = 0; i < 3; ++i)
        {
          straightenedVolume_RAS[i] = transformGridOrigin[i] + gridI * gridSpacing[0] * transformGridAxisX[i] +
                                      gridJ * gridSpacing[1] * transformGridAxisY[i] +
                                      gridK * gridSpacing[2] * transformGridAxisZ[i];
          inputVolume_RAS[i] = curvePoint_RAS[i] + (gridI - 0.5) * sliceSizeMm[0] * curveAxisX_RASVec[i] +
                               (gridJ - 0.5) * sliceSizeMm[1] * curveAxisY_RASVec[i];
        }
        if (reslicingPlanesModelNode)
        {
          if (gridI == 0 && gridJ == 0)
          {
            plane->SetOrigin(inputVolume_RAS);
          }
          else if (gridI == 1 && gridJ == 0)
          {
            plane->SetPoint1(inputVolume_RAS);
          }
          else if (gridI == 0 && gridJ == 1)
          {
            plane->SetPoint2(inputVolume_RAS);
          }
        }
        double difference_RAS[3];
        for (int i = 0; i < 3; ++i)
        {
          difference_RAS[i] = inputVolume_RAS[i] - straightenedVolume_RAS[i];
        }
        const int index = gridK * gridDimensions[1] * gridDimensions[0] + gridJ * gridDimensions[0] + gridI;
        transformDisplacements_RAS->SetTuple(index, difference_RAS);
      }
    }
    if (reslicingPlanesModelNode)
    {
      plane->Update();
      appender->AddInputData(plane->GetOutput());
    }
  }

  vtkGridTransform * transformGrid =
    vtkGridTransform::SafeDownCast(transformToStraightenedNode->GetTransformFromParent());
  vtkImageData * displacementGrid = transformGrid->GetDisplacementGrid();
  displacementGrid->GetPointData()->GetScalars()->Modified();
  displacementGrid->Modified();

  // delete temporary curve
  this->GetMRMLScene()->RemoveNode(resampledCurveNode);

  if (reslicingPlanesModelNode)
  {
    vtkSmartPointer<vtkAppendPolyData> appender = vtkSmartPointer<vtkAppendPolyData>::New();
    appender->Update();
    if (!reslicingPlanesModelNode->GetPolyData())
    {
      reslicingPlanesModelNode->CreateDefaultDisplayNodes();
      reslicingPlanesModelNode->GetDisplayNode()->SetVisibility2D(true);
    }
    reslicingPlanesModelNode->SetAndObservePolyData(appender->GetOutput());
  }
  return true;
}

//----------------------------------------------------------------------------
bool
vtkMRMLSliceLogic::CurvedPlanarReformationStraightenVolume(vtkMRMLScalarVolumeNode * outputStraightenedVolume,
                                                           vtkMRMLScalarVolumeNode * volumeNode,
                                                           const double              outputStraightenedVolumeSpacing[3],
                                                           vtkMRMLTransformNode *    straighteningTransformNode)
{
  // Compute straightened volume (useful for example for visualization of curved vessels)

  if (!outputStraightenedVolume || !volumeNode || !straighteningTransformNode)
  {
    vtkErrorMacro("vtkMRMLSliceLogic::CurvedPlanarReformationStraightenVolume failed: invalid input parameters");
    return false;
  }

  vtkOrientedGridTransform * gridTransform = vtkOrientedGridTransform::SafeDownCast(
    straighteningTransformNode->GetTransformFromParentAs("vtkOrientedGridTransform"));
  if (!gridTransform)
  {
    vtkErrorMacro("vtkMRMLSliceLogic::CurvedPlanarReformationStraightenVolume failed: straightening transform must "
                  "contain a vtkOrientedGridTransform from parent");
    return false;
  }

  // Get transformation grid geometry
  vtkMatrix4x4 * gridIjkToRasDirectionMatrix = gridTransform->GetGridDirectionMatrix();
  vtkImageData * gridTransformImage = gridTransform->GetDisplacementGrid();
  double         gridOrigin[3] = { 0.0, 0.0, 0.0 };
  gridTransformImage->GetOrigin(gridOrigin);
  double gridSpacing[3] = { 0.0, 0.0, 0.0 };
  gridTransformImage->GetSpacing(gridSpacing);
  int gridDimensions[3] = { 0, 0, 0 };
  gridTransformImage->GetDimensions(gridDimensions);
  const double gridExtentMm[3] = { gridSpacing[0] * (gridDimensions[0] - 1),
                                   gridSpacing[1] * (gridDimensions[1] - 1),
                                   gridSpacing[2] * (gridDimensions[2] - 1) };

  // Compute IJK to RAS matrix of output volume
  // Get grid axis directions
  vtkSmartPointer<vtkMatrix4x4> straightenedVolumeIJKToRASMatrix = vtkSmartPointer<vtkMatrix4x4>::New();
  straightenedVolumeIJKToRASMatrix->DeepCopy(gridIjkToRasDirectionMatrix);
  // Apply scaling
  for (int i = 0; i < 4; ++i)
  {
    for (int j = 0; j < 3; ++j)
    {
      straightenedVolumeIJKToRASMatrix->SetElement(
        i, j, straightenedVolumeIJKToRASMatrix->GetElement(i, j) * outputStraightenedVolumeSpacing[j]);
    }
  }
  // Set origin
  for (int i = 0; i < 3; ++i)
  {
    straightenedVolumeIJKToRASMatrix->SetElement(i, 3, gridOrigin[i]);
  }

  vtkSmartPointer<vtkImageData> outputStraightenedImageData = vtkSmartPointer<vtkImageData>::New();
  outputStraightenedImageData->SetExtent(0,
                                         static_cast<int>(gridExtentMm[0] / outputStraightenedVolumeSpacing[0]) - 1,
                                         0,
                                         static_cast<int>(gridExtentMm[1] / outputStraightenedVolumeSpacing[1]) - 1,
                                         0,
                                         static_cast<int>(gridExtentMm[2] / outputStraightenedVolumeSpacing[2]) - 1);
  outputStraightenedImageData->AllocateScalars(volumeNode->GetImageData()->GetScalarType(),
                                               volumeNode->GetImageData()->GetNumberOfScalarComponents());
  outputStraightenedVolume->SetAndObserveImageData(outputStraightenedImageData);
  outputStraightenedVolume->SetIJKToRASMatrix(straightenedVolumeIJKToRASMatrix);

  // Resample input volume to straightened volume
  vtkMRMLApplicationLogic * appLogic = this->GetMRMLApplicationLogic();
  std::string               resampleScalarVectorDWIVolumeString = "ResampleScalarVectorDWIVolume";
  bool                      found = appLogic->IsVolumeResamplerRegistered(resampleScalarVectorDWIVolumeString);
  if (!found)
  {
    vtkErrorMacro(
      "vtkMRMLSliceLogic::CurvedPlanarReformationStraightenVolume failed: failed to get CLI logic for module: "
      << resampleScalarVectorDWIVolumeString);
    return false;
  }

  std::string            resamplerName = resampleScalarVectorDWIVolumeString;
  vtkMRMLVolumeNode *    inputVolume = volumeNode;
  vtkMRMLVolumeNode *    outputVolume = outputStraightenedVolume;
  vtkMRMLTransformNode * resamplingTransform = straighteningTransformNode;
  vtkMRMLVolumeNode *    referenceVolume = outputStraightenedVolume;
  int                    interpolationType =
    (volumeNode->IsA("vtkMRMLLabelMapVolumeNode") ? vtkMRMLAbstractVolumeResampler::InterpolationTypeNearestNeighbor
                                                  : vtkMRMLAbstractVolumeResampler::InterpolationTypeBSpline);
  int windowedSincFunction = vtkMRMLAbstractVolumeResampler::WindowedSincFunctionCosine;
  const vtkMRMLAbstractVolumeResampler::ResamplingParameters resamplingParameters;

  bool success = appLogic->ResampleVolume(resamplerName,
                                          inputVolume,
                                          outputVolume,
                                          resamplingTransform,
                                          referenceVolume,
                                          interpolationType,
                                          windowedSincFunction,
                                          resamplingParameters);
  if (!success)
  {
    vtkErrorMacro("vtkMRMLSliceLogic::CurvedPlanarReformationStraightenVolume failed: CLI logic for module "
                  << resampleScalarVectorDWIVolumeString << " failed to run");
    return false;
  }

  outputStraightenedVolume->CreateDefaultDisplayNodes();
  vtkMRMLDisplayNode * volumeDisplayNode = volumeNode->GetDisplayNode();
  if (volumeDisplayNode)
  {
    outputStraightenedVolume->GetDisplayNode()->CopyContent(volumeDisplayNode);
  }
  return true;
}

//----------------------------------------------------------------------------
bool
vtkMRMLSliceLogic::CurvedPlanarReformationProjectVolume(vtkMRMLScalarVolumeNode * outputProjectedVolume,
                                                        vtkMRMLScalarVolumeNode * inputStraightenedVolume,
                                                        int                       projectionAxisIndex)
{
  // Create panoramic volume by mean intensity projection along an axis of the straightened volume

  if ((projectionAxisIndex < 0) || (projectionAxisIndex >= 3))
  {
    vtkErrorMacro("vtkMRMLSliceLogic::CurvedPlanarReformationProjectVolume failed: invalid input parameters");
    return false;
  }

  // Create a new vtkImageData for the projected volume
  vtkSmartPointer<vtkImageData> projectedImageData = vtkSmartPointer<vtkImageData>::New();
  outputProjectedVolume->SetAndObserveImageData(projectedImageData);

  // Get the image data from the input straightened volume
  vtkImageData * straightenedImageData = inputStraightenedVolume->GetImageData();
  if (!straightenedImageData)
  {
    vtkErrorMacro(
      "vtkMRMLSliceLogic::CurvedPlanarReformationProjectVolume failed: input straightened volume must have image data");
    return false;
  }

  // Get the dimensions of the straightened volume
  int outputImageDimensions[3] = { 0, 0, 0 };
  straightenedImageData->GetDimensions(outputImageDimensions);
  outputImageDimensions[projectionAxisIndex] = 1; // Set the projection axis to size 1
  projectedImageData->SetDimensions(outputImageDimensions);

  // Allocate scalars for the projected image
  projectedImageData->AllocateScalars(straightenedImageData->GetScalarType(),
                                      straightenedImageData->GetNumberOfScalarComponents());

  // Get arrays of the input and output volumes
  vtkSmartPointer<vtkDataArray> outputProjectedVolumeArray = projectedImageData->GetPointData()->GetScalars();
  vtkSmartPointer<vtkDataArray> inputStraightenedVolumeArray = straightenedImageData->GetPointData()->GetScalars();

  // Perform the projection (mean intensity projection along the specified axis)
  int dims[3] = { 0, 0, 0 };
  projectedImageData->GetDimensions(dims);

  if (projectionAxisIndex == 0)
  {
    for (int y = 0; y < dims[1]; ++y)
    {
      for (int z = 0; z < dims[2]; ++z)
      {
        double sum = 0.0;
        int    count = 0;
        for (int x = 0; x < dims[0]; ++x)
        {
          const int index = x + dims[0] * (y + dims[1] * z);
          sum += inputStraightenedVolumeArray->GetComponent(index, 0); // Assuming single component
          count++;
        }
        const int outputIndex = y + dims[1] * z;
        outputProjectedVolumeArray->SetComponent(outputIndex, 0, sum / count);
      }
    }
  }
  else if (projectionAxisIndex == 1)
  {
    for (int x = 0; x < dims[0]; ++x)
    {
      for (int z = 0; z < dims[2]; ++z)
      {
        double sum = 0.0;
        int    count = 0;
        for (int y = 0; y < dims[1]; ++y)
        {
          const int index = x + dims[0] * (y + dims[1] * z);
          sum += inputStraightenedVolumeArray->GetComponent(index, 0); // Assuming single component
          count++;
        }
        const int outputIndex = x + dims[0] * z;
        outputProjectedVolumeArray->SetComponent(outputIndex, 0, sum / count);
      }
    }
  }
  else
  {
    for (int x = 0; x < dims[0]; ++x)
    {
      for (int y = 0; y < dims[1]; ++y)
      {
        double sum = 0.0;
        int    count = 0;
        for (int z = 0; z < dims[2]; ++z)
        {
          int index = x + dims[0] * (y + dims[1] * z);
          sum += inputStraightenedVolumeArray->GetComponent(index, 0); // Assuming single component
          count++;
        }
        int outputIndex = x + dims[0] * y;
        outputProjectedVolumeArray->SetComponent(outputIndex, 0, sum / count);
      }
    }
  }

  // Mark the volume as modified
  outputProjectedVolume->GetImageData()->Modified();

  // Shift projection image into the center of the input image
  vtkSmartPointer<vtkMatrix4x4> ijkToRas = vtkSmartPointer<vtkMatrix4x4>::New();
  inputStraightenedVolume->GetIJKToRASMatrix(ijkToRas);

  double curvePointToWorldArray[4][4] = { 0.0 };
  for (int i = 0; i < 4; ++i)
  {
    for (int j = 0; i < 4; ++j)
    {
      curvePointToWorldArray[i][j] = ijkToRas->GetElement(i, j);
    }
  }

  double origin[3] = { 0.0, 0.0, 0.0 };
  for (int j = 0; j < 3; ++j)
  {
    origin[j] = curvePointToWorldArray[3][j];
  }

  double offsetToCenterDirectionVector[3] = { 0.0, 0.0, 0.0 };
  for (int j = 0; j < 3; ++j)
  {
    offsetToCenterDirectionVector[j] = curvePointToWorldArray[projectionAxisIndex][j];
  }

  double offsetToCenterDirectionLength = inputStraightenedVolume->GetImageData()->GetDimensions()[projectionAxisIndex] *
                                         inputStraightenedVolume->GetSpacing()[projectionAxisIndex];

  double newOrigin[3] = { 0.0, 0.0, 0.0 };
  for (int i = 0; i < 3; ++i)
  {
    newOrigin[i] = origin[i] + offsetToCenterDirectionVector[i] * offsetToCenterDirectionLength;
  }

  ijkToRas->SetElement(0, 3, newOrigin[0]);
  ijkToRas->SetElement(1, 3, newOrigin[1]);
  ijkToRas->SetElement(2, 3, newOrigin[2]);

  outputProjectedVolume->SetIJKToRASMatrix(ijkToRas);

  // Create default display nodes
  outputProjectedVolume->CreateDefaultDisplayNodes();

  return true;
}

//----------------------------------------------------------------------------
void vtkMRMLSliceLogic::UpdatePipeline()
{
  int modified = 0;
  if ( this->SliceCompositeNode )
  {
    // get the background and foreground image data from the layers
    // so we can use them as input to the image blend
    // TODO: change logic to use a volume node superclass rather than
    // a scalar volume node once the superclass is sorted out for vector/tensor Volumes

    const char *id;

    // Background
    id = this->SliceCompositeNode->GetBackgroundVolumeID();
    vtkMRMLVolumeNode *bgnode = nullptr;
    if (id)
    {
      bgnode = vtkMRMLVolumeNode::SafeDownCast (this->GetMRMLScene()->GetNodeByID(id));
    }

    if (this->BackgroundLayer)
    {
      if ( this->BackgroundLayer->GetVolumeNode() != bgnode )
      {
        this->BackgroundLayer->SetVolumeNode (bgnode);
        modified = 1;
      }
    }

    // Foreground
    id = this->SliceCompositeNode->GetForegroundVolumeID();
    vtkMRMLVolumeNode *fgnode = nullptr;
    if (id)
    {
      fgnode = vtkMRMLVolumeNode::SafeDownCast (this->GetMRMLScene()->GetNodeByID(id));
    }

    if (this->ForegroundLayer)
    {
      if ( this->ForegroundLayer->GetVolumeNode() != fgnode )
      {
        this->ForegroundLayer->SetVolumeNode (fgnode);
        modified = 1;
      }
    }

    // Label
    id = this->SliceCompositeNode->GetLabelVolumeID();
    vtkMRMLVolumeNode *lbnode = nullptr;
    if (id)
    {
      lbnode = vtkMRMLVolumeNode::SafeDownCast (this->GetMRMLScene()->GetNodeByID(id));
    }

    if (this->LabelLayer)
    {
      if ( this->LabelLayer->GetVolumeNode() != lbnode )
      {
        this->LabelLayer->SetVolumeNode (lbnode);
        modified = 1;
      }
    }

    /// set slice extents in the layers
    if (modified)
    {
      this->SetSliceExtentsToSliceNode();
    }

    // Now update the image blend with the background and foreground and label
    // -- layer 0 opacity is ignored, but since not all inputs may be non-0,
    //    we keep track so that someone could, for example, have a 0 background
    //    with a non-0 foreground and label and everything will work with the
    //    label opacity
    //

    vtkAlgorithmOutput* backgroundImagePort = this->BackgroundLayer ? this->BackgroundLayer->GetImageDataConnection() : nullptr;
    vtkAlgorithmOutput* foregroundImagePort = this->ForegroundLayer ? this->ForegroundLayer->GetImageDataConnection() : nullptr;

    vtkAlgorithmOutput* backgroundImagePortUVW = this->BackgroundLayer ? this->BackgroundLayer->GetImageDataConnectionUVW() : nullptr;
    vtkAlgorithmOutput* foregroundImagePortUVW = this->ForegroundLayer ? this->ForegroundLayer->GetImageDataConnectionUVW() : nullptr;

    vtkAlgorithmOutput* labelImagePort = this->LabelLayer ? this->LabelLayer->GetImageDataConnection() : nullptr;
    vtkAlgorithmOutput* labelImagePortUVW = this->LabelLayer ? this->LabelLayer->GetImageDataConnectionUVW() : nullptr;

    std::deque<SliceLayerInfo> layers;
    std::deque<SliceLayerInfo> layersUVW;

    this->Pipeline->AddLayers(layers, this->SliceCompositeNode->GetCompositing(), this->SliceCompositeNode->GetClipToBackgroundVolume(),
      backgroundImagePort, foregroundImagePort, this->SliceCompositeNode->GetForegroundOpacity(),
      labelImagePort, this->SliceCompositeNode->GetLabelOpacity());
    this->PipelineUVW->AddLayers(layersUVW, this->SliceCompositeNode->GetCompositing(), this->SliceCompositeNode->GetClipToBackgroundVolume(),
      backgroundImagePortUVW, foregroundImagePortUVW, this->SliceCompositeNode->GetForegroundOpacity(),
      labelImagePortUVW, this->SliceCompositeNode->GetLabelOpacity());

    // Check fraction changes for add/subtract pipeline
    if (this->UpdateFractions(this->Pipeline->ForegroundFractionMath.GetPointer(), this->SliceCompositeNode->GetForegroundOpacity()))
    {
      modified = 1;
    }
    if (this->UpdateFractions(this->PipelineUVW->ForegroundFractionMath.GetPointer(), this->SliceCompositeNode->GetForegroundOpacity()))
    {
      modified = 1;
    }

    if (this->UpdateBlendLayers(this->Pipeline->Blend.GetPointer(), layers, this->SliceCompositeNode->GetClipToBackgroundVolume()))
    {
      modified = 1;
    }
    if (this->UpdateBlendLayers(this->PipelineUVW->Blend.GetPointer(), layersUVW, this->SliceCompositeNode->GetClipToBackgroundVolume()))
    {
      modified = 1;
    }

    //Models
    this->UpdateImageData();
    vtkMRMLDisplayNode* displayNode = this->SliceModelNode ? this->SliceModelNode->GetModelDisplayNode() : nullptr;
    if ( displayNode && this->SliceNode )
    {
      displayNode->SetVisibility( this->SliceNode->GetSliceVisible() );
      displayNode->SetViewNodeIDs( this->SliceNode->GetThreeDViewIDs());
      if ( (this->SliceNode->GetSliceResolutionMode() != vtkMRMLSliceNode::SliceResolutionMatch2DView &&
          !((backgroundImagePortUVW != nullptr) || (foregroundImagePortUVW != nullptr) || (labelImagePortUVW != nullptr) ) ) ||
          (this->SliceNode->GetSliceResolutionMode() == vtkMRMLSliceNode::SliceResolutionMatch2DView &&
          !((backgroundImagePort != nullptr) || (foregroundImagePort != nullptr) || (labelImagePort != nullptr) ) ))
      {
        displayNode->SetTextureImageDataConnection(nullptr);
      }
      else if (displayNode->GetTextureImageDataConnection() != this->ExtractModelTexture->GetOutputPort())
      {
        displayNode->SetTextureImageDataConnection(this->ExtractModelTexture->GetOutputPort());
      }
        if ( this->LabelLayer && this->LabelLayer->GetImageDataConnection())
        {
          displayNode->SetInterpolateTexture(0);
        }
        else
        {
          displayNode->SetInterpolateTexture(1);
        }
    }
    if ( modified )
    {
      if (this->SliceModelNode && this->SliceModelNode->GetPolyData())
      {
        this->SliceModelNode->GetPolyData()->Modified();
      }
      this->Modified();
    }
  }
}

//----------------------------------------------------------------------------
void vtkMRMLSliceLogic::PrintSelf(ostream& os, vtkIndent indent)
{
  this->Superclass::PrintSelf(os, indent);
  vtkIndent nextIndent;
  nextIndent = indent.GetNextIndent();

  os << indent << "SlicerSliceLogic:             " << this->GetClassName() << "\n";

  if (this->SliceNode)
  {
    os << indent << "SliceNode: ";
    os << (this->SliceNode->GetID() ? this->SliceNode->GetID() : "(0 ID)") << "\n";
    this->SliceNode->PrintSelf(os, nextIndent);
  }
  else
  {
    os << indent << "SliceNode: (none)\n";
  }

  if (this->SliceCompositeNode)
  {
    os << indent << "SliceCompositeNode: ";
    os << (this->SliceCompositeNode->GetID() ? this->SliceCompositeNode->GetID() : "(0 ID)") << "\n";
    this->SliceCompositeNode->PrintSelf(os, nextIndent);
  }
  else
  {
    os << indent << "SliceCompositeNode: (none)\n";
  }

  if (this->BackgroundLayer)
  {
    os << indent << "BackgroundLayer: ";
    this->BackgroundLayer->PrintSelf(os, nextIndent);
  }
  else
  {
    os << indent << "BackgroundLayer: (none)\n";
  }

  if (this->ForegroundLayer)
  {
    os << indent << "ForegroundLayer: ";
    this->ForegroundLayer->PrintSelf(os, nextIndent);
  }
  else
  {
    os << indent << "ForegroundLayer: (none)\n";
  }

  if (this->LabelLayer)
  {
    os << indent << "LabelLayer: ";
    this->LabelLayer->PrintSelf(os, nextIndent);
  }
  else
  {
    os << indent << "LabelLayer: (none)\n";
  }

  if (this->Pipeline->Blend.GetPointer())
  {
    os << indent << "Blend: ";
    this->Pipeline->Blend->PrintSelf(os, nextIndent);
  }
  else
  {
    os << indent << "Blend: (none)\n";
  }

  if (this->PipelineUVW->Blend.GetPointer())
  {
    os << indent << "BlendUVW: ";
    this->PipelineUVW->Blend->PrintSelf(os, nextIndent);
  }
  else
  {
    os << indent << "BlendUVW: (none)\n";
  }

  os << indent << "SLICE_MODEL_NODE_NAME_SUFFIX: " << this->SLICE_MODEL_NODE_NAME_SUFFIX << "\n";

}

//----------------------------------------------------------------------------
void vtkMRMLSliceLogic::DeleteSliceModel()
{
  // Remove References
  if (this->SliceModelNode != nullptr)
  {
    this->SliceModelNode->SetAndObserveDisplayNodeID(nullptr);
    this->SliceModelNode->SetAndObserveTransformNodeID(nullptr);
    this->SliceModelNode->SetPolyDataConnection(nullptr);
  }
  if (this->SliceModelDisplayNode != nullptr)
  {
    this->SliceModelDisplayNode->SetTextureImageDataConnection(nullptr);
  }

  // Remove Nodes
  if (this->SliceModelNode != nullptr)
  {
    if (this->GetMRMLScene() && this->GetMRMLScene()->IsNodePresent(this->SliceModelNode))
    {
      this->GetMRMLScene()->RemoveNode(this->SliceModelNode);
    }
    this->SliceModelNode->Delete();
    this->SliceModelNode = nullptr;
  }
  if (this->SliceModelDisplayNode != nullptr)
  {
    if (this->GetMRMLScene() && this->GetMRMLScene()->IsNodePresent(this->SliceModelDisplayNode))
    {
      this->GetMRMLScene()->RemoveNode(this->SliceModelDisplayNode);
    }
    this->SliceModelDisplayNode->Delete();
    this->SliceModelDisplayNode = nullptr;
  }
  if (this->SliceModelTransformNode != nullptr)
  {
    if (this->GetMRMLScene() && this->GetMRMLScene()->IsNodePresent(this->SliceModelTransformNode))
    {
      this->GetMRMLScene()->RemoveNode(this->SliceModelTransformNode);
    }
    this->SliceModelTransformNode->Delete();
    this->SliceModelTransformNode = nullptr;
  }
}

//----------------------------------------------------------------------------
void vtkMRMLSliceLogic::CreateSliceModel()
{
  if(!this->GetMRMLScene())
  {
    return;
  }

  if (this->SliceModelNode != nullptr &&
      this->GetMRMLScene()->GetNodeByID(this->GetSliceModelNode()->GetID()) == nullptr )
  {
    this->DeleteSliceModel();
  }

  if ( this->SliceModelNode == nullptr)
  {
    this->SliceModelNode = vtkMRMLModelNode::New();
    this->SliceModelNode->SetScene(this->GetMRMLScene());
    this->SliceModelNode->SetDisableModifiedEvent(1);

    this->SliceModelNode->SetHideFromEditors(1);
    // allow point picking (e.g., placing a markups point on the slice node)
    this->SliceModelNode->SetSelectable(1);
    this->SliceModelNode->SetSaveWithScene(0);

    // create plane slice
    vtkNew<vtkPlaneSource> planeSource;
    planeSource->Update();
    this->SliceModelNode->SetPolyDataConnection(planeSource->GetOutputPort());
    this->SliceModelNode->SetDisableModifiedEvent(0);

    // create display node and set texture
    vtkMRMLSliceDisplayNode* sliceDisplayNode = vtkMRMLSliceDisplayNode::SafeDownCast(this->GetMRMLScene()->CreateNodeByClass("vtkMRMLSliceDisplayNode"));
    this->SliceModelDisplayNode = sliceDisplayNode;
    this->SliceModelDisplayNode->SetScene(this->GetMRMLScene());
    this->SliceModelDisplayNode->SetDisableModifiedEvent(1);

    //this->SliceModelDisplayNode->SetInputPolyData(this->SliceModelNode->GetOutputPolyData());
    this->SliceModelDisplayNode->SetVisibility(0);
    this->SliceModelDisplayNode->SetOpacity(1);
    this->SliceModelDisplayNode->SetColor(1,1,1);

    // Show intersecting slices in new slice views if this is currently enabled in the application.
    vtkMRMLApplicationLogic* appLogic = this->GetMRMLApplicationLogic();
    if (appLogic)
    {
      // Intersection
      sliceDisplayNode->SetIntersectingSlicesVisibility(appLogic->GetIntersectingSlicesEnabled(vtkMRMLApplicationLogic::IntersectingSlicesVisibility));
      sliceDisplayNode->SetIntersectingSlicesInteractive(appLogic->GetIntersectingSlicesEnabled(vtkMRMLApplicationLogic::IntersectingSlicesInteractive));
      sliceDisplayNode->SetIntersectingSlicesTranslationEnabled(appLogic->GetIntersectingSlicesEnabled(vtkMRMLApplicationLogic::IntersectingSlicesTranslation));
      sliceDisplayNode->SetIntersectingSlicesRotationEnabled(appLogic->GetIntersectingSlicesEnabled(vtkMRMLApplicationLogic::IntersectingSlicesRotation));
      // ThickSlab
      sliceDisplayNode->SetIntersectingThickSlabInteractive(appLogic->GetIntersectingSlicesEnabled(vtkMRMLApplicationLogic::IntersectingSlicesThickSlabInteractive));
      // TODO: curved planar reformation too?
    }

    std::string displayName = "Slice Display";
    std::string modelNodeName = "Slice " + this->SLICE_MODEL_NODE_NAME_SUFFIX;
    std::string transformNodeName = "Slice Transform";
    if (this->SliceNode && this->SliceNode->GetLayoutName())
    {
      // Auto-set the colors based on the slice node
      this->SliceModelDisplayNode->SetColor(this->SliceNode->GetLayoutColor());
      displayName = this->SliceNode->GetLayoutName() + std::string(" Display");
      modelNodeName = this->SliceNode->GetLayoutName() + std::string(" ") + this->SLICE_MODEL_NODE_NAME_SUFFIX;
      transformNodeName = this->SliceNode->GetLayoutName() + std::string(" Transform");
    }
    this->SliceModelDisplayNode->SetAmbient(1);
    this->SliceModelDisplayNode->SetBackfaceCulling(0);
    this->SliceModelDisplayNode->SetDiffuse(0);
    this->SliceModelDisplayNode->SetTextureImageDataConnection(this->ExtractModelTexture->GetOutputPort());
    this->SliceModelDisplayNode->SetSaveWithScene(0);
    this->SliceModelDisplayNode->SetDisableModifiedEvent(0);
    // set an attribute to distinguish this from regular model display nodes
    this->SliceModelDisplayNode->SetAttribute("SliceLogic.IsSliceModelDisplayNode", "True");
    this->SliceModelDisplayNode->SetName(this->GetMRMLScene()->GenerateUniqueName(displayName).c_str());

    this->SliceModelNode->SetName(modelNodeName.c_str());

    // make the xy to RAS transform
    this->SliceModelTransformNode = vtkMRMLLinearTransformNode::New();
    this->SliceModelTransformNode->SetScene(this->GetMRMLScene());
    this->SliceModelTransformNode->SetDisableModifiedEvent(1);

    this->SliceModelTransformNode->SetHideFromEditors(1);
    this->SliceModelTransformNode->SetSelectable(0);
    this->SliceModelTransformNode->SetSaveWithScene(0);
    // set the transform for the slice model for use by an image actor in the viewer
    vtkNew<vtkMatrix4x4> identity;
    identity->Identity();
    this->SliceModelTransformNode->SetMatrixTransformToParent(identity.GetPointer());
    this->SliceModelTransformNode->SetName(this->GetMRMLScene()->GenerateUniqueName(transformNodeName).c_str());

    this->SliceModelTransformNode->SetDisableModifiedEvent(0);

  }

  if (this->SliceModelNode != nullptr && this->GetMRMLScene()->GetNodeByID( this->GetSliceModelNode()->GetID() ) == nullptr )
  {
    this->AddingSliceModelNodes = true;
    this->GetMRMLScene()->AddNode(this->SliceModelDisplayNode);
    this->GetMRMLScene()->AddNode(this->SliceModelTransformNode);
    this->SliceModelNode->SetAndObserveDisplayNodeID(this->SliceModelDisplayNode->GetID());
    this->GetMRMLScene()->AddNode(this->SliceModelNode);
    this->AddingSliceModelNodes = false;
    this->SliceModelDisplayNode->SetTextureImageDataConnection(this->ExtractModelTexture->GetOutputPort());
    this->SliceModelNode->SetAndObserveTransformNodeID(this->SliceModelTransformNode->GetID());
  }

  // update the description to refer back to the slice and composite nodes
  // TODO: this doesn't need to be done unless the ID change, but it needs
  // to happen after they have been set, so do it every event for now
  if ( this->SliceModelNode != nullptr )
  {
    std::string description;
    std::stringstream ssD;
    if (this->SliceNode && this->SliceNode->GetID() )
    {
      ssD << " SliceID " << this->SliceNode->GetID();
    }
    if (this->SliceCompositeNode && this->SliceCompositeNode->GetID() )
    {
      ssD << " CompositeID " << this->SliceCompositeNode->GetID();
    }

    std::getline(ssD, description);
    this->SliceModelNode->SetDescription(description.c_str());
  }
}

//----------------------------------------------------------------------------
vtkMRMLVolumeNode *vtkMRMLSliceLogic::GetLayerVolumeNode(int layer)
{
  if (!this->SliceNode || !this->SliceCompositeNode)
  {
    return (nullptr);
  }

  const char *id = nullptr;
  switch (layer)
  {
    case LayerBackground:
    {
      id = this->SliceCompositeNode->GetBackgroundVolumeID();
      break;
    }
    case LayerForeground:
    {
      id = this->SliceCompositeNode->GetForegroundVolumeID();
      break;
    }
    case LayerLabel:
    {
      id = this->SliceCompositeNode->GetLabelVolumeID();
      break;
    }
  }
  vtkMRMLScene* scene = this->GetMRMLScene();
  return scene ? vtkMRMLVolumeNode::SafeDownCast(
    scene->GetNodeByID( id )) : nullptr;
}

//----------------------------------------------------------------------------
// Get the size of the volume, transformed to RAS space
void vtkMRMLSliceLogic::GetVolumeRASBox(vtkMRMLVolumeNode *volumeNode, double rasDimensions[3], double rasCenter[3])
{
  rasCenter[0] = rasDimensions[0] = 0.0;
  rasCenter[1] = rasDimensions[1] = 0.0;
  rasCenter[2] = rasDimensions[2] = 0.0;


  vtkImageData *volumeImage;
  if ( !volumeNode || ! (volumeImage = volumeNode->GetImageData()) )
  {
    return;
  }

  double bounds[6];
  volumeNode->GetRASBounds(bounds);

  for (int i=0; i<3; i++)
  {
    rasDimensions[i] = bounds[2*i+1] - bounds[2*i];
    rasCenter[i] = 0.5*(bounds[2*i+1] + bounds[2*i]);
  }
}

//----------------------------------------------------------------------------
// Get the size of the volume, transformed to RAS space
void vtkMRMLSliceLogic::GetVolumeSliceDimensions(vtkMRMLVolumeNode *volumeNode,
  double sliceDimensions[3], double sliceCenter[3])
{
  sliceCenter[0] = sliceDimensions[0] = 0.0;
  sliceCenter[1] = sliceDimensions[1] = 0.0;
  sliceCenter[2] = sliceDimensions[2] = 0.0;

  double sliceBounds[6];
  this->GetVolumeSliceBounds(volumeNode, sliceBounds);

  for (int i = 0; i < 3; i++)
  {
    sliceDimensions[i] = sliceBounds[2*i+1] - sliceBounds[2*i];
    sliceCenter[i] = 0.5*(sliceBounds[2*i+1] + sliceBounds[2*i]);
  }
}

//----------------------------------------------------------------------------
void vtkMRMLSliceLogic::GetVolumeSliceBounds(vtkMRMLVolumeNode *volumeNode,
  double sliceBounds[6], bool useVoxelCenter/*=false*/)
{
  if (this->SliceNode == nullptr || volumeNode == nullptr)
  {
    sliceBounds[0] = sliceBounds[1] = 0.0;
    sliceBounds[2] = sliceBounds[3] = 0.0;
    sliceBounds[4] = sliceBounds[5] = 0.0;
    return;
  }
  //
  // figure out how big that volume is on this particular slice plane
  //
  vtkNew<vtkMatrix4x4> rasToSlice;
  rasToSlice->DeepCopy(this->SliceNode->GetSliceToRAS());
  rasToSlice->SetElement(0, 3, 0.0);
  rasToSlice->SetElement(1, 3, 0.0);
  rasToSlice->SetElement(2, 3, 0.0);
  rasToSlice->Invert();

  volumeNode->GetSliceBounds(sliceBounds, rasToSlice.GetPointer(), useVoxelCenter);
}

//----------------------------------------------------------------------------
// Get the spacing of the volume, transformed to slice space
double *vtkMRMLSliceLogic::GetVolumeSliceSpacing(vtkMRMLVolumeNode *volumeNode)
{
  if ( !volumeNode )
  {
    return (this->SliceSpacing);
  }

  if (!this->SliceNode)
  {
    return (this->SliceSpacing);
  }

  if (this->SliceNode->GetSliceSpacingMode() == vtkMRMLSliceNode::PrescribedSliceSpacingMode)
  {
    // jvm - should we cache the PrescribedSliceSpacing in SliceSpacing?
    double *pspacing = this->SliceNode->GetPrescribedSliceSpacing();
    this->SliceSpacing[0] = pspacing[0];
    this->SliceSpacing[1] = pspacing[1];
    this->SliceSpacing[2] = pspacing[2];
    return (pspacing);
  }

  // Compute slice spacing from the volume axis closest matching the slice axis, projected to the slice axis.

  vtkNew<vtkMatrix4x4> ijkToWorld;
  volumeNode->GetIJKToRASMatrix(ijkToWorld);

  // Apply transform to the volume axes, if the volume is transformed with a linear transform
  vtkMRMLTransformNode *transformNode = volumeNode->GetParentTransformNode();
  if ( transformNode != nullptr &&  transformNode->IsTransformToWorldLinear() )
  {
    vtkNew<vtkMatrix4x4> volumeRASToWorld;
    transformNode->GetMatrixTransformToWorld(volumeRASToWorld);
    //rasToRAS->Invert();
    vtkMatrix4x4::Multiply4x4(volumeRASToWorld, ijkToWorld, ijkToWorld);
  }

  vtkNew<vtkMatrix4x4> worldToIJK;
  vtkMatrix4x4::Invert(ijkToWorld, worldToIJK);
  vtkNew<vtkMatrix4x4> sliceToIJK;
  vtkMatrix4x4::Multiply4x4(worldToIJK, this->SliceNode->GetSliceToRAS(), sliceToIJK);
  vtkNew<vtkMatrix4x4> ijkToSlice;
  vtkMatrix4x4::Invert(sliceToIJK, ijkToSlice);

  // Find the volume IJK axis that has the most similar direction to the slice axis.
  // Use the spacing component of this volume IJK axis parallel to the slice axis.
  double scale[3]; // unused
  vtkAddonMathUtilities::NormalizeOrientationMatrixColumns(sliceToIJK, scale);
  // after normalization, sliceToIJK only contains slice axis directions
  for (int sliceAxisIndex = 0; sliceAxisIndex < 3; sliceAxisIndex++)
  {
    // Slice axis direction in IJK coordinate system
    double sliceAxisDirection_I = fabs(sliceToIJK->GetElement(0, sliceAxisIndex));
    double sliceAxisDirection_J = fabs(sliceToIJK->GetElement(1, sliceAxisIndex));
    double sliceAxisDirection_K = fabs(sliceToIJK->GetElement(2, sliceAxisIndex));
    if (sliceAxisDirection_I > sliceAxisDirection_J)
    {
      if (sliceAxisDirection_I > sliceAxisDirection_K)
      {
        // this sliceAxis direction is closest volume I axis direction
        this->SliceSpacing[sliceAxisIndex] = fabs(ijkToSlice->GetElement(sliceAxisIndex, 0 /*I*/));
      }
      else
      {
        // this sliceAxis direction is closest volume K axis direction
        this->SliceSpacing[sliceAxisIndex] = fabs(ijkToSlice->GetElement(sliceAxisIndex, 2 /*K*/));
      }
    }
    else
    {
      if (sliceAxisDirection_J > sliceAxisDirection_K)
      {
        // this sliceAxis direction is closest volume J axis direction
        this->SliceSpacing[sliceAxisIndex] = fabs(ijkToSlice->GetElement(sliceAxisIndex, 1 /*J*/));
      }
      else
      {
        // this sliceAxis direction is closest volume K axis direction
        this->SliceSpacing[sliceAxisIndex] = fabs(ijkToSlice->GetElement(sliceAxisIndex, 2 /*K*/));
      }
    }
  }

  return this->SliceSpacing;
}

//----------------------------------------------------------------------------
// adjust the node's field of view to match the extent of current volume
void vtkMRMLSliceLogic::FitSliceToVolume(vtkMRMLVolumeNode *volumeNode, int width, int height)
{
  vtkImageData *volumeImage;
  if (!volumeNode || !(volumeImage = volumeNode->GetImageData()))
  {
    return;
  }

  if (!this->SliceNode)
  {
    return;
  }

  double rasDimensions[3], rasCenter[3];
  this->GetVolumeRASBox(volumeNode, rasDimensions, rasCenter);
  double sliceDimensions[3], sliceCenter[3];
  this->GetVolumeSliceDimensions(volumeNode, sliceDimensions, sliceCenter);

  double fitX, fitY, fitZ, displayX, displayY;
  displayX = fitX = fabs(sliceDimensions[0]);
  displayY = fitY = fabs(sliceDimensions[1]);
  fitZ = this->GetVolumeSliceSpacing(volumeNode)[2] * this->SliceNode->GetDimensions()[2];


  // fit fov to min dimension of window
  double pixelSize;
  if (height > width)
  {
    pixelSize = fitX / (1.0 * width);
    fitY = pixelSize * height;
  }
  else
  {
    pixelSize = fitY / (1.0 * height);
    fitX = pixelSize * width;
  }

  // if volume is still too big, shrink some more
  if (displayX > fitX)
  {
    fitY = fitY / (fitX / (displayX * 1.0));
    fitX = displayX;
  }
  if (displayY > fitY)
  {
    fitX = fitX / (fitY / (displayY * 1.0));
    fitY = displayY;
  }

  this->SliceNode->SetFieldOfView(fitX, fitY, fitZ);

  //
  // set the origin to be the center of the volume in RAS
  //
  vtkNew<vtkMatrix4x4> sliceToRAS;
  sliceToRAS->DeepCopy(this->SliceNode->GetSliceToRAS());
  sliceToRAS->SetElement(0, 3, rasCenter[0]);
  sliceToRAS->SetElement(1, 3, rasCenter[1]);
  sliceToRAS->SetElement(2, 3, rasCenter[2]);
  this->SliceNode->GetSliceToRAS()->DeepCopy(sliceToRAS.GetPointer());
  this->SliceNode->SetSliceOrigin(0,0,0);
  //sliceNode->SetSliceOffset(offset);

  // TODO: Fit UVW space
  this->SnapSliceOffsetToIJK();
  this->SliceNode->UpdateMatrices( );
}

//----------------------------------------------------------------------------
void vtkMRMLSliceLogic::FitSliceToVolumes(vtkCollection *volumeNodes, int width, int height)
{
  if (!this->SliceNode)
  {
    return;
  }

  if (volumeNodes->GetNumberOfItems() == 0)
  {
    return;
  }

  double rasCenter[3] = {0., 0., 0.};
  double sliceBounds[6] = {0., 0., 0., 0., 0., 0.};
  double sliceDimensions[3] = {0., 0., 0.};
  double sliceSpacingZ = 0.;
  int volumeCount = 0;

  vtkSmartPointer<vtkCollectionIterator> iterator = vtkSmartPointer<vtkCollectionIterator>::New();
  iterator->SetCollection(volumeNodes);

  bool firstVolumeFound = false;
  for (iterator->InitTraversal(); !iterator->IsDoneWithTraversal(); iterator->GoToNextItem())
  {
    vtkMRMLVolumeNode* volumeNode = vtkMRMLVolumeNode::SafeDownCast(iterator->GetCurrentObject());
    if (!volumeNode || !volumeNode->GetImageData())
    {
      continue;
    }

    double volumeRasDimensions[3], volumeRasCenter[3];
    this->GetVolumeRASBox(volumeNode, volumeRasDimensions, volumeRasCenter);
    double volumeSliceBounds[6];
    this->GetVolumeSliceBounds(volumeNode, volumeSliceBounds);

    // Accumulate the center coordinates
    vtkMath::Add(rasCenter, volumeRasCenter, rasCenter);
    volumeCount++;

    // Track the slice dimensions
    for (int i = 0; i < 3; i++)
    {
      sliceBounds[2*i] = std::min(sliceBounds[2*i], volumeSliceBounds[2*i]);
      sliceBounds[2*i+1] = std::max(sliceBounds[2*i+1], volumeSliceBounds[2*i+1]);
    }

    // Set sliceSpacingZ for the first volume found
    if (!firstVolumeFound)
    {
      sliceSpacingZ = this->GetVolumeSliceSpacing(volumeNode)[2];
      firstVolumeFound = true;
    }
  }

  // Calculate the barycenter of the centers
  if (volumeCount > 0)
  {
    vtkMath::MultiplyScalar(rasCenter, 1.0 / volumeCount);
  }

  // Calculate the slice dimensions for all volumes
  for (int i = 0; i < 3; i++)
  {
    sliceDimensions[i] = (sliceBounds[2*i+1] - sliceBounds[2*i]) * 1.05; // 5% margin
  }

  double fitX, fitY, fitZ, displayX, displayY;
  displayX = fitX = fabs(sliceDimensions[0]);
  displayY = fitY = fabs(sliceDimensions[1]);
  fitZ = sliceSpacingZ * this->SliceNode->GetDimensions()[2];

  // fit fov to min dimension of window
  double pixelSize;
  if (height > width)
  {
    pixelSize = fitX / (1.0 * width);
    fitY = pixelSize * height;
  }
  else
  {
    pixelSize = fitY / (1.0 * height);
    fitX = pixelSize * width;
  }

  // if volume is still too big, shrink some more
  if (displayX > fitX)
  {
    fitY = fitY / (fitX / (displayX * 1.0));
    fitX = displayX;
  }
  if (displayY > fitY)
  {
    fitX = fitX / (fitY / (displayY * 1.0));
    fitY = displayY;
  }

  this->SliceNode->SetFieldOfView(fitX, fitY, fitZ);

  //
  // set the origin to be the center of the volume in RAS
  //
  vtkNew<vtkMatrix4x4> sliceToRAS;
  sliceToRAS->DeepCopy(this->SliceNode->GetSliceToRAS());
  sliceToRAS->SetElement(0, 3, rasCenter[0]);
  sliceToRAS->SetElement(1, 3, rasCenter[1]);
  sliceToRAS->SetElement(2, 3, rasCenter[2]);
  this->SliceNode->GetSliceToRAS()->DeepCopy(sliceToRAS.GetPointer());
  this->SliceNode->SetSliceOrigin(0,0,0);
  //sliceNode->SetSliceOffset(offset);

  // TODO: Fit UVW space
  this->SnapSliceOffsetToIJK();
  this->SliceNode->UpdateMatrices();
}

//----------------------------------------------------------------------------
// Get the size of the volume, transformed to RAS space
void vtkMRMLSliceLogic::GetBackgroundRASBox(double rasDimensions[3], double rasCenter[3])
{
  vtkMRMLVolumeNode *backgroundNode = nullptr;
  backgroundNode = this->GetLayerVolumeNode(0);
  this->GetVolumeRASBox(backgroundNode, rasDimensions, rasCenter);
}

//----------------------------------------------------------------------------
// Get the size of the volume, transformed to RAS space
void vtkMRMLSliceLogic::GetBackgroundSliceDimensions(double sliceDimensions[3], double sliceCenter[3])
{
  vtkMRMLVolumeNode *backgroundNode = nullptr;
  backgroundNode = this->GetLayerVolumeNode(0);
  this->GetVolumeSliceDimensions(backgroundNode, sliceDimensions, sliceCenter);
}

//----------------------------------------------------------------------------
// Get the spacing of the volume, transformed to slice space
double *vtkMRMLSliceLogic::GetBackgroundSliceSpacing()
{
  vtkMRMLVolumeNode *backgroundNode = nullptr;
  backgroundNode = this->GetLayerVolumeNode(0);
  return (this->GetVolumeSliceSpacing(backgroundNode));
}

//----------------------------------------------------------------------------
void vtkMRMLSliceLogic::GetBackgroundSliceBounds(double sliceBounds[6])
{
  vtkMRMLVolumeNode *backgroundNode = nullptr;
  backgroundNode = this->GetLayerVolumeNode(0);
  this->GetVolumeSliceBounds(backgroundNode, sliceBounds);
}

//----------------------------------------------------------------------------
// adjust the node's field of view to match the extent of the first selected volume (background, foregorund, labelmap)
void vtkMRMLSliceLogic::FitSliceToFirst(int width, int height)
{
  // Use SliceNode dimensions if width and height parameters are omitted
  if (width < 0 || height < 0)
  {
    int* dimensions = this->SliceNode->GetDimensions();
    width = dimensions ? dimensions[0] : -1;
    height = dimensions ? dimensions[1] : -1;
  }

  if (width < 0 || height < 0)
  {
    vtkErrorMacro(<< __FUNCTION__ << "- Invalid size:" << width
                  << "x" << height);
    return;
  }

  vtkMRMLVolumeNode *node = nullptr;
  node = this->GetLayerVolumeNode(0);
  if (!node)
  {
    node = this->GetLayerVolumeNode(1);
  }
  if (!node)
  {
    node = this->GetLayerVolumeNode(2);
  }
  this->FitSliceToVolume(node, width, height);
}

//----------------------------------------------------------------------------
// adjust the node's field of view to match the extent of current background volume
void vtkMRMLSliceLogic::FitSliceToBackground(int width, int height)
{
  // Use SliceNode dimensions if width and height parameters are omitted
  if (width < 0 || height < 0)
  {
    int* dimensions = this->SliceNode->GetDimensions();
    width = dimensions ? dimensions[0] : -1;
    height = dimensions ? dimensions[1] : -1;
  }

  if (width < 0 || height < 0)
  {
    vtkErrorMacro(<< __FUNCTION__ << "- Invalid size:" << width
                  << "x" << height);
    return;
  }

  vtkMRMLVolumeNode *backgroundNode = nullptr;
  backgroundNode = this->GetLayerVolumeNode(0);
  this->FitSliceToVolume(backgroundNode, width, height);
}

//----------------------------------------------------------------------------
// adjust the node's field of view to match the extent of all volume layers
void vtkMRMLSliceLogic::FitSliceToAll(int width, int height)
{
  // Use SliceNode dimensions if width and height parameters are omitted
  if (width < 0 || height < 0)
  {
    int* dimensions = this->SliceNode->GetDimensions();
    width = dimensions ? dimensions[0] : -1;
    height = dimensions ? dimensions[1] : -1;
  }

  if (width < 0 || height < 0)
  {
    vtkErrorMacro(<< __FUNCTION__ << "- Invalid size:" << width
                  << "x" << height);
    return;
  }

  vtkNew<vtkCollection> volumeNodes;
  for (int layer = 0; layer < 3; layer++)
  {
    vtkMRMLVolumeNode *volumeNode = this->GetLayerVolumeNode(layer);
    if (volumeNode)
    {
      volumeNodes->AddItem(volumeNode);
    }
  }

  this->FitSliceToVolumes(volumeNodes, width, height);
}

//----------------------------------------------------------------------------
void vtkMRMLSliceLogic::FitFOVToBackground(double fov)
{
  // get backgroundNode  and imagedata
  vtkMRMLScalarVolumeNode* backgroundNode =
    vtkMRMLScalarVolumeNode::SafeDownCast(
      this->GetMRMLScene()->GetNodeByID(
        this->SliceCompositeNode->GetBackgroundVolumeID() ));
  vtkImageData *backgroundImage =
    backgroundNode ? backgroundNode->GetImageData() : nullptr;
  if (!backgroundImage)
  {
    return;
  }
  // get viewer's width and height. we may be using a LightBox
  // display, so base width and height on renderer0 in the SliceViewer.
  int width = this->SliceNode->GetDimensions()[0];
  int height = this->SliceNode->GetDimensions()[1];

  int dimensions[3];
  double rasDimensions[4];
  double doubleDimensions[4];
  vtkNew<vtkMatrix4x4> ijkToRAS;

  // what are the actual dimensions of the imagedata?
  backgroundImage->GetDimensions(dimensions);
  doubleDimensions[0] = static_cast<double>(dimensions[0]);
  doubleDimensions[1] = static_cast<double>(dimensions[1]);
  doubleDimensions[2] = static_cast<double>(dimensions[2]);
  doubleDimensions[3] = 0.0;
  backgroundNode->GetIJKToRASMatrix(ijkToRAS.GetPointer());
  ijkToRAS->MultiplyPoint(doubleDimensions, rasDimensions);

  // and what are their slice dimensions?
  vtkNew<vtkMatrix4x4> rasToSlice;
  double sliceDimensions[4];
  rasToSlice->DeepCopy(this->SliceNode->GetSliceToRAS());
  rasToSlice->SetElement(0, 3, 0.0);
  rasToSlice->SetElement(1, 3, 0.0);
  rasToSlice->SetElement(2, 3, 0.0);
  rasToSlice->Invert();
  rasToSlice->MultiplyPoint(rasDimensions, sliceDimensions);

  double fovh, fovv;
  // which is bigger, slice viewer width or height?
  // assign user-specified fov to smaller slice window
  // dimension
  if ( width < height )
  {
    fovh = fov;
    fovv = fov * height/width;
  }
  else
  {
    fovv = fov;
    fovh = fov * width/height;
  }
  // we want to compute the slice dimensions of the
  // user-specified fov (note that the slice node's z field of
  // view is NOT changed)
  this->SliceNode->SetFieldOfView(fovh, fovv, this->SliceNode->GetFieldOfView()[2]);

  vtkNew<vtkMatrix4x4> sliceToRAS;
  sliceToRAS->DeepCopy(this->SliceNode->GetSliceToRAS());
  this->SliceNode->GetSliceToRAS()->DeepCopy(sliceToRAS.GetPointer());
}

//----------------------------------------------------------------------------
void vtkMRMLSliceLogic::ResizeSliceNode(double newWidth, double newHeight)
{
  if (!this->SliceNode)
  {
    return;
  }

  // New size must be the active slice vtkRenderer size. It's the same than the window
  // if the layout is 1x1.
  newWidth /= this->SliceNode->GetLayoutGridColumns();
  newHeight /= this->SliceNode->GetLayoutGridRows();

  int oldDimensions[3];
  this->SliceNode->GetDimensions(oldDimensions);
  double oldFOV[3];
  this->SliceNode->GetFieldOfView(oldFOV);
  double newFOV[3];
  newFOV[0] = oldFOV[0];
  newFOV[1] = oldFOV[1];
  newFOV[2] = this->SliceSpacing[2] * oldDimensions[2];
  double windowAspect = (newWidth != 0. ? newHeight / newWidth : 1.);
  double planeAspect = (newFOV[0] != 0. ? newFOV[1] / newFOV[0] : 1.);
  if (windowAspect != planeAspect)
  {
    newFOV[0] = (windowAspect != 0. ? newFOV[1] / windowAspect : newFOV[0]);
  }
  int disabled = this->SliceNode->StartModify();
  this->SliceNode->SetDimensions(newWidth, newHeight, oldDimensions[2]);
  this->SliceNode->SetFieldOfView(newFOV[0], newFOV[1], newFOV[2]);
  this->SliceNode->EndModify(disabled);
}

//----------------------------------------------------------------------------
double *vtkMRMLSliceLogic::GetLowestVolumeSliceSpacing()
{
  // TBD: Doesn't return the lowest slice spacing, just the first valid spacing
  vtkMRMLVolumeNode *volumeNode;
  for ( int layer=0; layer < 3; layer++ )
  {
    volumeNode = this->GetLayerVolumeNode (layer);
    if (volumeNode)
    {
      return this->GetVolumeSliceSpacing( volumeNode );
    }
  }
  return (this->SliceSpacing);
}

//----------------------------------------------------------------------------
void vtkMRMLSliceLogic::GetLowestVolumeSliceBounds(double sliceBounds[6], bool useVoxelCenter/*=false*/)
{
  vtkMRMLVolumeNode *volumeNode;
  for ( int layer=0; layer < 3; layer++ )
  {
    volumeNode = this->GetLayerVolumeNode (layer);
    if (volumeNode)
    {
      return this->GetVolumeSliceBounds(volumeNode, sliceBounds, useVoxelCenter);
    }
  }
  // return the default values
  return this->GetVolumeSliceBounds(nullptr, sliceBounds, useVoxelCenter);
}

#define LARGE_BOUNDS_NUM 1.0e10
#define SMALL_BOUNDS_NUM -1.0e10
//----------------------------------------------------------------------------
void vtkMRMLSliceLogic::GetSliceBounds(double sliceBounds[6])
{
  int i;
  for (i=0; i<3; i++)
  {
    sliceBounds[2*i]   = LARGE_BOUNDS_NUM;
    sliceBounds[2*i+1] = SMALL_BOUNDS_NUM;
  }

  vtkMRMLVolumeNode *volumeNode;
  for ( int layer=0; layer < 3; layer++ )
  {
    volumeNode = this->GetLayerVolumeNode (layer);
    if (volumeNode)
    {
      double bounds[6];
      this->GetVolumeSliceBounds( volumeNode, bounds );
      for (i=0; i<3; i++)
      {
        if (bounds[2*i] < sliceBounds[2*i])
        {
          sliceBounds[2*i] = bounds[2*i];
        }
        if (bounds[2*i+1] > sliceBounds[2*i+1])
        {
          sliceBounds[2*i+1] = bounds[2*i+1];
        }
      }
    }
  }

  // default
  for (i=0; i<3; i++)
  {
    if (sliceBounds[2*i] == LARGE_BOUNDS_NUM)
    {
      sliceBounds[2*i] = -100;
    }
    if (sliceBounds[2*i+1] == SMALL_BOUNDS_NUM)
    {
      sliceBounds[2*i+1] = 100;
    }
  }

}

//----------------------------------------------------------------------------
// Get/Set the current distance from the origin to the slice plane
double vtkMRMLSliceLogic::GetSliceOffset()
{
  // this method has been moved to vtkMRMLSliceNode
  // the API stays for backwards compatibility

  if ( !this->SliceNode )
  {
    return 0.0;
  }

  return this->SliceNode->GetSliceOffset();

}

//----------------------------------------------------------------------------
void vtkMRMLSliceLogic::SetSliceOffset(double offset)
{
  // this method has been moved to vtkMRMLSliceNode
  // the API stays for backwards compatibility
  if (!this->SliceNode)
  {
    return;
  }
  this->SliceNode->SetSliceOffset(offset);
}

//----------------------------------------------------------------------------
void vtkMRMLSliceLogic::StartSliceCompositeNodeInteraction(unsigned int parameters)
{
  if (!this->SliceCompositeNode)
  {
    return;
  }

  // Cache the flags on what parameters are going to be modified. Need
  // to this this outside the conditional on HotLinkedControl and LinkedControl
  this->SliceCompositeNode->SetInteractionFlags(parameters);

  // If we have hot linked controls, then we want to broadcast changes
  if (this->SliceCompositeNode->GetHotLinkedControl() && this->SliceCompositeNode->GetLinkedControl())
  {
    this->SliceCompositeNode->InteractingOn();
  }
}

//----------------------------------------------------------------------------
void vtkMRMLSliceLogic::EndSliceCompositeNodeInteraction()
{
  if (!this->SliceCompositeNode)
  {
    return;
  }
  // If we have linked controls, then we want to broadcast changes
  if (this->SliceCompositeNode->GetLinkedControl())
  {
    // Need to trigger a final message to broadcast to all the nodes
    // that are linked
    this->SliceCompositeNode->InteractingOn();
    this->SliceCompositeNode->Modified();
    this->SliceCompositeNode->InteractingOff();
  }

  this->SliceCompositeNode->SetInteractionFlags(0);
}

//----------------------------------------------------------------------------
void vtkMRMLSliceLogic::StartSliceNodeInteraction(unsigned int parameters)
{
  if (this->SliceNode == nullptr || this->SliceCompositeNode == nullptr)
  {
    return;
  }

  // Cache the flags on what parameters are going to be modified. Need
  // to this this outside the conditional on HotLinkedControl and LinkedControl
  this->SliceNode->SetInteractionFlags(parameters);

  // If we have hot linked controls, then we want to broadcast changes
  if ((this->SliceCompositeNode->GetHotLinkedControl() || parameters == vtkMRMLSliceNode::MultiplanarReformatFlag)
      && this->SliceCompositeNode->GetLinkedControl())
  {
    this->SliceNode->InteractingOn();
  }
}

//----------------------------------------------------------------------------
void vtkMRMLSliceLogic::SetSliceExtentsToSliceNode()
{
  if (this->SliceNode == nullptr)
  {
    return;
  }

  double sliceBounds[6];
  this->GetSliceBounds( sliceBounds );

  double extents[3];
  extents[0] = sliceBounds[1] - sliceBounds[0];
  extents[1] = sliceBounds[3] - sliceBounds[2];
  extents[2] = sliceBounds[5] - sliceBounds[4];

  if (this->SliceNode->GetSliceResolutionMode() == vtkMRMLSliceNode::SliceResolutionMatch2DView)
  {
    this->SliceNode->SetUVWExtentsAndDimensions(this->SliceNode->GetFieldOfView(),
                                                this->SliceNode->GetUVWDimensions());
  }
 else if (this->SliceNode->GetSliceResolutionMode() == vtkMRMLSliceNode::SliceResolutionMatchVolumes)
 {
    double *spacing = this->GetLowestVolumeSliceSpacing();
    double minSpacing = spacing[0];
    minSpacing = minSpacing < spacing[1] ? minSpacing:spacing[1];
    minSpacing = minSpacing < spacing[2] ? minSpacing:spacing[2];

    int sliceResolutionMax = 200;
    if (minSpacing > 0.0)
    {
      double maxExtent = extents[0];
      maxExtent = maxExtent > extents[1] ? maxExtent:extents[1];
      maxExtent = maxExtent > extents[2] ? maxExtent:extents[2];

      sliceResolutionMax = maxExtent/minSpacing;
    }
    int dimensions[]={sliceResolutionMax, sliceResolutionMax, 1};

    this->SliceNode->SetUVWExtentsAndDimensions(extents, dimensions);
 }
  else if (this->SliceNode->GetSliceResolutionMode() == vtkMRMLSliceNode::SliceFOVMatch2DViewSpacingMatchVolumes)
  {
    double *spacing = this->GetLowestVolumeSliceSpacing();
    double minSpacing = spacing[0];
    minSpacing = minSpacing < spacing[1] ? minSpacing:spacing[1];
    minSpacing = minSpacing < spacing[2] ? minSpacing:spacing[2];

    double fov[3];
    int dimensions[]={0,0,1};
    this->SliceNode->GetFieldOfView(fov);
    for (int i=0; i<2; i++)
    {
       dimensions[i] = ceil(fov[i]/minSpacing +0.5);
    }
    this->SliceNode->SetUVWExtentsAndDimensions(fov, dimensions);
  }
  else if (this->SliceNode->GetSliceResolutionMode() == vtkMRMLSliceNode::SliceFOVMatchVolumesSpacingMatch2DView)
  {
    // compute RAS spacing in 2D view
    vtkMatrix4x4 *xyToRAS = this->SliceNode->GetXYToRAS();
    int  dims[3];

    //
    double inPoint[4]={0,0,0,1};
    double outPoint0[4];
    double outPoint1[4];
    double outPoint2[4];

    // set the z position to be the active slice (from the lightbox)
    inPoint[2] = this->SliceNode->GetActiveSlice();

    // transform XYZ = (0,0,0)
    xyToRAS->MultiplyPoint(inPoint, outPoint0);

    // transform XYZ = (1,0,0)
    inPoint[0] = 1;
    xyToRAS->MultiplyPoint(inPoint, outPoint1);

    // transform XYZ = (0,1,0)
    inPoint[0] = 0;
    inPoint[1] = 1;
    xyToRAS->MultiplyPoint(inPoint, outPoint2);

    double xSpacing = sqrt(vtkMath::Distance2BetweenPoints(outPoint0, outPoint1));
    double ySpacing = sqrt(vtkMath::Distance2BetweenPoints(outPoint0, outPoint2));

    dims[0] = extents[0]/xSpacing+1;
    dims[1] = extents[2]/ySpacing+1;
    dims[2] = 1;

    this->SliceNode->SetUVWExtentsAndDimensions(extents, dims);
  }

}

//----------------------------------------------------------------------------
void vtkMRMLSliceLogic::EndSliceNodeInteraction()
{
  if (this->SliceNode == nullptr || this->SliceCompositeNode == nullptr)
  {
    return;
  }

  // If we have linked controls, then we want to broadcast changes
  if (this->SliceCompositeNode->GetLinkedControl())
  {
    // Need to trigger a final message to broadcast to all the nodes
    // that are linked
    this->SliceNode->InteractingOn();
    this->SliceNode->Modified();
    this->SliceNode->InteractingOff();
  }

  this->SliceNode->SetInteractionFlags(0);
}

//----------------------------------------------------------------------------
void vtkMRMLSliceLogic::StartSliceOffsetInteraction()
{
  // This method is here in case we want to do something specific when
  // we start SliceOffset interactions

  this->StartSliceNodeInteraction(vtkMRMLSliceNode::SliceToRASFlag);
}

//----------------------------------------------------------------------------
void vtkMRMLSliceLogic::EndSliceOffsetInteraction()
{
  // This method is here in case we want to do something specific when
  // we complete SliceOffset interactions

  this->EndSliceNodeInteraction();
}

//----------------------------------------------------------------------------
void vtkMRMLSliceLogic::SnapSliceOffsetToIJK()
{
  double offset, *spacing, bounds[6];
  double oldOffset = this->GetSliceOffset();
  spacing = this->GetLowestVolumeSliceSpacing();
  this->GetLowestVolumeSliceBounds( bounds );

  // number of slices along the offset dimension (depends on ijkToRAS and Transforms)
  // - find the slice index corresponding to the current slice offset
  // - move the offset to the middle of that slice
  // - note that bounds[4] 'furthest' edge of the volume from the point of view of this slice
  // - note also that spacing[2] may correspond to i, j, or k depending on ijkToRAS and sliceToRAS
  double slice = (oldOffset - bounds[4]) / spacing[2];
  int intSlice = static_cast<int> (slice);
  offset = (intSlice + 0.5) * spacing[2] + bounds[4];
  this->SetSliceOffset( offset );
}


//----------------------------------------------------------------------------
std::vector< vtkMRMLDisplayNode*> vtkMRMLSliceLogic::GetPolyDataDisplayNodes()
{
  std::vector< vtkMRMLDisplayNode*> nodes;
  std::vector<vtkMRMLSliceLayerLogic *> layerLogics;
  layerLogics.push_back(this->GetBackgroundLayer());
  layerLogics.push_back(this->GetForegroundLayer());
  for (unsigned int i=0; i<layerLogics.size(); i++)
  {
    vtkMRMLSliceLayerLogic *layerLogic = layerLogics[i];
    if (layerLogic && layerLogic->GetVolumeNode())
    {
      vtkMRMLVolumeNode *volumeNode = vtkMRMLVolumeNode::SafeDownCast (layerLogic->GetVolumeNode());
      vtkMRMLGlyphableVolumeDisplayNode *displayNode = vtkMRMLGlyphableVolumeDisplayNode::SafeDownCast( layerLogic->GetVolumeNode()->GetDisplayNode() );
      if (displayNode)
      {
        std::vector< vtkMRMLGlyphableVolumeSliceDisplayNode*> dnodes  = displayNode->GetSliceGlyphDisplayNodes(volumeNode);
        for (unsigned int n=0; n<dnodes.size(); n++)
        {
          vtkMRMLGlyphableVolumeSliceDisplayNode* dnode = dnodes[n];
          if (layerLogic->GetSliceNode()
            && layerLogic->GetSliceNode()->GetLayoutName()
            && !strcmp(layerLogic->GetSliceNode()->GetLayoutName(), dnode->GetName()) )
          {
            nodes.push_back(dnode);
          }
        }
      }//  if (volumeNode)
    }// if (layerLogic && layerLogic->GetVolumeNode())
  }
  return nodes;
}

//----------------------------------------------------------------------------
int vtkMRMLSliceLogic::GetSliceIndexFromOffset(double sliceOffset, vtkMRMLVolumeNode *volumeNode)
{
  if ( !volumeNode )
  {
    return SLICE_INDEX_NO_VOLUME;
  }
  vtkImageData *volumeImage=nullptr;
  if ( !(volumeImage = volumeNode->GetImageData()) )
  {
    return SLICE_INDEX_NO_VOLUME;
  }
  if (!this->SliceNode)
  {
    return SLICE_INDEX_NO_VOLUME;
  }

  vtkNew<vtkMatrix4x4> ijkToRAS;
  volumeNode->GetIJKToRASMatrix (ijkToRAS.GetPointer());
  vtkMRMLTransformNode *transformNode = volumeNode->GetParentTransformNode();
  if ( transformNode )
  {
    vtkNew<vtkMatrix4x4> rasToRAS;
    transformNode->GetMatrixTransformToWorld(rasToRAS.GetPointer());
    vtkMatrix4x4::Multiply4x4 (rasToRAS.GetPointer(), ijkToRAS.GetPointer(), ijkToRAS.GetPointer());
  }

  // Get the slice normal in RAS

  vtkNew<vtkMatrix4x4> rasToSlice;
  rasToSlice->DeepCopy(this->SliceNode->GetSliceToRAS());
  rasToSlice->Invert();

  double sliceNormal_IJK[4]={0,0,1,0};  // slice normal vector in IJK coordinate system
  double sliceNormal_RAS[4]={0,0,0,0};  // slice normal vector in RAS coordinate system
  this->SliceNode->GetSliceToRAS()->MultiplyPoint(sliceNormal_IJK, sliceNormal_RAS);

  // Find an axis normal that has the same orientation as the slice normal
  double axisDirection_RAS[3]={0,0,0};
  int axisIndex=0;
  double volumeSpacing=1.0; // spacing along axisIndex
  for (axisIndex=0; axisIndex<3; axisIndex++)
  {
    axisDirection_RAS[0]=ijkToRAS->GetElement(0,axisIndex);
    axisDirection_RAS[1]=ijkToRAS->GetElement(1,axisIndex);
    axisDirection_RAS[2]=ijkToRAS->GetElement(2,axisIndex);
    volumeSpacing=vtkMath::Norm(axisDirection_RAS); // spacing along axisIndex
    vtkMath::Normalize(sliceNormal_RAS);
    vtkMath::Normalize(axisDirection_RAS);
    double dotProd=vtkMath::Dot(sliceNormal_RAS, axisDirection_RAS);
    // Due to numerical inaccuracies the dot product of two normalized vectors
    // can be slightly bigger than 1 (and acos cannot be computed) - fix that.
    if (dotProd>1.0)
    {
      dotProd=1.0;
    }
    else if (dotProd<-1.0)
    {
      dotProd=-1.0;
    }
    double axisMisalignmentDegrees=acos(dotProd)*180.0/vtkMath::Pi();
    if (fabs(axisMisalignmentDegrees)<0.1)
    {
      // found an axis that is aligned to the slice normal
      break;
    }
    if (fabs(axisMisalignmentDegrees-180)<0.1 || fabs(axisMisalignmentDegrees+180)<0.1)
    {
      // found an axis that is aligned to the slice normal, just points to the opposite direction
      volumeSpacing*=-1.0;
      break;
    }
  }

  if (axisIndex>=3)
  {
    // no aligned axis is found
    return SLICE_INDEX_ROTATED;
  }

  // Determine slice index
  double originPos_RAS[4]={
    ijkToRAS->GetElement( 0, 3 ),
    ijkToRAS->GetElement( 1, 3 ),
    ijkToRAS->GetElement( 2, 3 ),
    0};
  double originPos_Slice[4]={0,0,0,0};
  rasToSlice->MultiplyPoint(originPos_RAS, originPos_Slice);
  double volumeOriginOffset=originPos_Slice[2];
  double sliceShift=sliceOffset-volumeOriginOffset;
  double normalizedSliceShift=sliceShift/volumeSpacing;
  int sliceIndex=vtkMath::Round(normalizedSliceShift)+1; // +0.5 because the slice plane is displayed in the center of the slice

  // Check if slice index is within the volume
  int sliceCount=volumeImage->GetDimensions()[axisIndex];
  if (sliceIndex<1 || sliceIndex>sliceCount)
  {
    sliceIndex=SLICE_INDEX_OUT_OF_VOLUME;
  }

  return sliceIndex;
}

//----------------------------------------------------------------------------
// sliceIndex: DICOM slice index, 1-based
int vtkMRMLSliceLogic::GetSliceIndexFromOffset(double sliceOffset)
{
  vtkMRMLVolumeNode *volumeNode;
  for (int layer=0; layer < 3; layer++ )
  {
    volumeNode = this->GetLayerVolumeNode (layer);
    if (volumeNode)
    {
      int sliceIndex=this->GetSliceIndexFromOffset( sliceOffset, volumeNode );
      // return the result for the first available layer
      return sliceIndex;
    }
  }
  // slice is not aligned to any of the layers or out of the volume
  return SLICE_INDEX_NO_VOLUME;
}

//----------------------------------------------------------------------------
vtkMRMLSliceCompositeNode* vtkMRMLSliceLogic
::GetSliceCompositeNode(vtkMRMLSliceNode* sliceNode)
{
  return sliceNode ? vtkMRMLSliceLogic::GetSliceCompositeNode(
    sliceNode->GetScene(), sliceNode->GetLayoutName()) : nullptr;
}

//----------------------------------------------------------------------------
vtkMRMLSliceCompositeNode* vtkMRMLSliceLogic
::GetSliceCompositeNode(vtkMRMLScene* scene, const char* layoutName)
{
  if (!scene || !layoutName)
  {
    return nullptr;
  }
  vtkMRMLNode* node;
  vtkCollectionSimpleIterator it;
  for (scene->GetNodes()->InitTraversal(it);
       (node = (vtkMRMLNode*)scene->GetNodes()->GetNextItemAsObject(it)) ;)
  {
    vtkMRMLSliceCompositeNode* sliceCompositeNode =
      vtkMRMLSliceCompositeNode::SafeDownCast(node);
    if (sliceCompositeNode &&
        sliceCompositeNode->GetLayoutName() &&
        !strcmp(sliceCompositeNode->GetLayoutName(), layoutName))
    {
      return sliceCompositeNode;
    }
  }
  return nullptr;
}

//----------------------------------------------------------------------------
vtkMRMLSliceNode* vtkMRMLSliceLogic
::GetSliceNode(vtkMRMLSliceCompositeNode* sliceCompositeNode)
{
  if (!sliceCompositeNode)
  {
    return nullptr;
  }
  return sliceCompositeNode ? vtkMRMLSliceLogic::GetSliceNode(
    sliceCompositeNode->GetScene(), sliceCompositeNode->GetLayoutName()) : nullptr;
}

//----------------------------------------------------------------------------
vtkMRMLSliceNode* vtkMRMLSliceLogic
::GetSliceNode(vtkMRMLScene* scene, const char* layoutName)
{
  if (!scene || !layoutName)
  {
    return nullptr;
  }
  vtkObject* itNode = nullptr;
  vtkCollectionSimpleIterator it;
  for (scene->GetNodes()->InitTraversal(it); (itNode = scene->GetNodes()->GetNextItemAsObject(it));)
  {
    vtkMRMLSliceNode* sliceNode = vtkMRMLSliceNode::SafeDownCast(itNode);
    if (!sliceNode)
    {
      continue;
    }
    if (sliceNode->GetLayoutName() &&
      !strcmp(sliceNode->GetLayoutName(), layoutName))
    {
      return sliceNode;
    }
  }
  return nullptr;
}

//----------------------------------------------------------------------------
bool vtkMRMLSliceLogic::IsSliceModelNode(vtkMRMLNode *mrmlNode)
{
  if (mrmlNode != nullptr &&
      mrmlNode->IsA("vtkMRMLModelNode") &&
      mrmlNode->GetName() != nullptr &&
      strstr(mrmlNode->GetName(), vtkMRMLSliceLogic::SLICE_MODEL_NODE_NAME_SUFFIX.c_str()) != nullptr)
  {
    return true;
  }
  return false;
}

//----------------------------------------------------------------------------
bool vtkMRMLSliceLogic::IsSliceModelDisplayNode(vtkMRMLDisplayNode *mrmlDisplayNode)
{
  if (vtkMRMLSliceDisplayNode::SafeDownCast(mrmlDisplayNode))
  {
    return true;
  }
  if (mrmlDisplayNode != nullptr &&
      mrmlDisplayNode->IsA("vtkMRMLModelDisplayNode"))
  {
    const char *attrib = mrmlDisplayNode->GetAttribute("SliceLogic.IsSliceModelDisplayNode");
    // allow the attribute to be set to anything but 0
    if (attrib != nullptr &&
        strcmp(attrib, "0") != 0)
    {
      return true;
    }
  }
  return false;
}

//----------------------------------------------------------------------------
vtkImageBlend* vtkMRMLSliceLogic::GetBlend()
{
  return this->Pipeline->Blend.GetPointer();
}

//----------------------------------------------------------------------------
vtkImageBlend* vtkMRMLSliceLogic::GetBlendUVW()
{
  return this->PipelineUVW->Blend.GetPointer();
}

//----------------------------------------------------------------------------
void vtkMRMLSliceLogic::RotateSliceToLowestVolumeAxes(bool forceSlicePlaneToSingleSlice/*=true*/)
{
  vtkMRMLVolumeNode* volumeNode;
  for (int layer = 0; layer < 3; layer++)
  {
    volumeNode = this->GetLayerVolumeNode(layer);
    if (volumeNode)
    {
      break;
    }
  }
  if (!volumeNode)
  {
    return;
  }
  vtkMRMLSliceNode* sliceNode = this->GetSliceNode();
  if (!sliceNode)
  {
    return;
  }
  sliceNode->RotateToVolumePlane(volumeNode, forceSlicePlaneToSingleSlice);
  this->SnapSliceOffsetToIJK();
}

//----------------------------------------------------------------------------
int vtkMRMLSliceLogic::GetEditableLayerAtWorldPosition(double worldPos[3],
  bool backgroundVolumeEditable/*=true*/, bool foregroundVolumeEditable/*=true*/)
{
  vtkMRMLSliceNode *sliceNode = this->GetSliceNode();
  if (!sliceNode)
  {
    return vtkMRMLSliceLogic::LayerNone;
  }
  vtkMRMLSliceCompositeNode *sliceCompositeNode = this->GetSliceCompositeNode();
  if (!sliceCompositeNode)
  {
    return vtkMRMLSliceLogic::LayerNone;
  }

  if (!foregroundVolumeEditable && !backgroundVolumeEditable)
  {
    // window/level editing is disabled on both volumes
    return vtkMRMLSliceLogic::LayerNone;
  }
  // By default adjust background volume, if available
  bool adjustForeground = !backgroundVolumeEditable || !sliceCompositeNode->GetBackgroundVolumeID();

  // If both foreground and background volumes are visible then choose adjustment of
  // foreground volume, if foreground volume is visible in current mouse position
  if (sliceCompositeNode->GetBackgroundVolumeID() && sliceCompositeNode->GetForegroundVolumeID())
  {
    if (foregroundVolumeEditable && backgroundVolumeEditable)
    {
    adjustForeground = (sliceCompositeNode->GetForegroundOpacity() >= 0.01)
      && this->IsEventInsideVolume(true, worldPos)   // inside background (used as mask for displaying foreground)
      && this->vtkMRMLSliceLogic::IsEventInsideVolume(false, worldPos); // inside foreground
    }
  }

  return (adjustForeground ? vtkMRMLSliceLogic::LayerForeground : vtkMRMLSliceLogic::LayerBackground);
}

//----------------------------------------------------------------------------
bool vtkMRMLSliceLogic::IsEventInsideVolume(bool background, double worldPos[3])
{
  vtkMRMLSliceNode *sliceNode = this->GetSliceNode();
  if (!sliceNode)
  {
    return false;
  }
  vtkMRMLSliceLayerLogic* layerLogic = background ?
    this->GetBackgroundLayer() : this->GetForegroundLayer();
  if (!layerLogic)
  {
    return false;
  }
  vtkMRMLVolumeNode* volumeNode = layerLogic->GetVolumeNode();
  if (!volumeNode || !volumeNode->GetImageData())
  {
    return false;
  }

  vtkNew<vtkGeneralTransform> inputVolumeIJKToWorldTransform;
  inputVolumeIJKToWorldTransform->PostMultiply();

  vtkNew<vtkMatrix4x4> inputVolumeIJK2RASMatrix;
  volumeNode->GetIJKToRASMatrix(inputVolumeIJK2RASMatrix);
  inputVolumeIJKToWorldTransform->Concatenate(inputVolumeIJK2RASMatrix);

  vtkNew<vtkGeneralTransform> inputVolumeRASToWorld;
  vtkMRMLTransformNode::GetTransformBetweenNodes(volumeNode->GetParentTransformNode(), nullptr, inputVolumeRASToWorld);
  inputVolumeIJKToWorldTransform->Concatenate(inputVolumeRASToWorld);

  double ijkPos[3] = { 0.0, 0.0, 0.0 };
  inputVolumeIJKToWorldTransform->GetInverse()->TransformPoint(worldPos, ijkPos);

  int volumeExtent[6] = { 0 };
  volumeNode->GetImageData()->GetExtent(volumeExtent);
  for (int i = 0; i < 3; i++)
  {
    // In VTK, the voxel coordinate refers to the center of the voxel and so the image bounds
    // go beyond the position of the first and last voxels by half voxel. Therefore include 0.5 shift.
    if (ijkPos[i] < volumeExtent[i * 2] - 0.5 || ijkPos[i] > volumeExtent[i * 2 + 1] + 0.5)
    {
      return false;
    }
  }
  return true;
}

//----------------------------------------------------------------------------
vtkMRMLSliceDisplayNode* vtkMRMLSliceLogic::GetSliceDisplayNode()
{
  return vtkMRMLSliceDisplayNode::SafeDownCast(this->GetSliceModelDisplayNode());
}


//----------------------------------------------------------------------------
bool vtkMRMLSliceLogic::GetSliceOffsetRangeResolution(double range[2], double& resolution)
{
  // Calculate the number of slices in the current range.
  // Extent is between the farthest voxel centers (not voxel sides).
  double sliceBounds[6] = {0, -1, 0, -1, 0, -1};
  this->GetLowestVolumeSliceBounds(sliceBounds, true);

  const double * sliceSpacing = this->GetLowestVolumeSliceSpacing();
  if (!sliceSpacing)
  {
    range[0] = -1.0;
    range[1] = 1.0;
    resolution = 1.0;
    return false;
  }

  // Set the scale increments to match the z spacing (rotated into slice space)
  resolution = sliceSpacing ? sliceSpacing[2] : 1.0;

  bool singleSlice = ((sliceBounds[5] - sliceBounds[4]) < resolution);
  if (singleSlice)
  {
    // add one blank slice before and after the current slice to make the slider appear in the center when
    // we are centered on the slice
    double centerPos = (sliceBounds[4] + sliceBounds[5]) / 2.0;
    range[0] = centerPos - resolution;
    range[1] = centerPos + resolution;
  }
  else
  {
    // there are at least two slices in the range
    range[0] = sliceBounds[4];
    range[1] = sliceBounds[5];
  }

  return true;
}
