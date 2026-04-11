#pragma once
#include "Core.h"


Result<AEGP_RenderOptionsH> getRenderOptions(Result<AEGP_ItemH> itemH);
Result<AEGP_LayerRenderOptionsH> getLayerRenderOptions(Result<AEGP_LayerH> layerH);

Result<AEGP_RenderOptionsH> setTime(Result<AEGP_RenderOptionsH> roH, float time);
Result<AEGP_LayerRenderOptionsH> setLayerTime(Result<AEGP_LayerRenderOptionsH> roH, float time);

Result<AEGP_RenderOptionsH> getWorldType(Result<AEGP_RenderOptionsH> roH);

Result<AEGP_RenderOptionsH> setDownsampleFactor(Result<AEGP_RenderOptionsH> roH, int x, int y);
Result<AEGP_LayerRenderOptionsH> setLayerDownsampleFactor(Result<AEGP_LayerRenderOptionsH> roH, int x, int y);

Result<AEGP_RenderOptionsH> setWorldType(Result<AEGP_RenderOptionsH> roH, AEGP_WorldType type);
Result<AEGP_LayerRenderOptionsH> setLayerWorldType(Result<AEGP_LayerRenderOptionsH> roH, AEGP_WorldType type);

Result<void> disposeRenderOptions(Result <AEGP_RenderOptionsH> roH);
Result<void> disposeLayerRenderOptions(Result<AEGP_LayerRenderOptionsH> roH);
