#pragma once
#include "Core.h"

// ── Mask Suite ──
Result<int> getLayerNumMasks(Result<AEGP_LayerH> layerH);
Result<AEGP_MaskRefH> getLayerMaskByIndex(Result<AEGP_LayerH> layerH, int mask_index);
Result<AEGP_MaskRefH> createNewMask(Result<AEGP_LayerH> layerH);
Result<void> deleteMask(Result<AEGP_MaskRefH> maskH);
Result<bool> getMaskInvert(Result<AEGP_MaskRefH> maskH);
Result<void> setMaskInvert(Result<AEGP_MaskRefH> maskH, bool invert);
Result<int> getMaskMode(Result<AEGP_MaskRefH> maskH);
Result<void> setMaskMode(Result<AEGP_MaskRefH> maskH, int mode);
Result<void> disposeMask(Result<AEGP_MaskRefH> maskH);

// ── Mask Stream ──
Result<AEGP_StreamRefH> getNewMaskStream(Result<AEGP_MaskRefH> maskH, int which_stream);
// which_stream: 400=OUTLINE, 401=OPACITY, 402=FEATHER, 403=EXPANSION

// ── Mask Outline Suite ──
Result<bool> isMaskOutlineOpen(Result<AEGP_MaskOutlineValH> outlineH);
Result<void> setMaskOutlineOpen(Result<AEGP_MaskOutlineValH> outlineH, bool open);
Result<int> getMaskOutlineNumSegments(Result<AEGP_MaskOutlineValH> outlineH);
Result<AEGP_MaskVertex> getMaskOutlineVertexInfo(Result<AEGP_MaskOutlineValH> outlineH, int which_point);
Result<void> setMaskOutlineVertexInfo(Result<AEGP_MaskOutlineValH> outlineH, int which_point, const AEGP_MaskVertex* vertexP);
Result<void> createMaskOutlineVertex(Result<AEGP_MaskOutlineValH> outlineH, int position);
Result<void> deleteMaskOutlineVertex(Result<AEGP_MaskOutlineValH> outlineH, int index);
