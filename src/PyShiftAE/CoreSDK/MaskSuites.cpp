#include "MaskSuites.h"

// ── Mask Suite ──

Result<int> getLayerNumMasks(Result<AEGP_LayerH> layerH)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    A_Err err = A_Err_NONE;
    A_long num = 0;
    ERR(suites.MaskSuite6()->AEGP_GetLayerNumMasks(layerH.value, &num));
    Result<int> result;
    result.value = static_cast<int>(num);
    result.error = err;
    return result;
}

Result<AEGP_MaskRefH> getLayerMaskByIndex(Result<AEGP_LayerH> layerH, int mask_index)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    AEGP_PluginID* pluginIDPtr = SuiteManager::GetInstance().GetPluginID();
    A_Err err = A_Err_NONE;
    AEGP_MaskRefH maskH = NULL;
    ERR(suites.MaskSuite6()->AEGP_GetLayerMaskByIndex(layerH.value, static_cast<AEGP_MaskIndex>(mask_index), &maskH));
    Result<AEGP_MaskRefH> result;
    result.value = maskH;
    result.error = err;
    return result;
}

Result<AEGP_MaskRefH> createNewMask(Result<AEGP_LayerH> layerH)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    A_Err err = A_Err_NONE;
    AEGP_MaskRefH maskH = NULL;
    A_long new_index = 0;
    ERR(suites.MaskSuite6()->AEGP_CreateNewMask(layerH.value, &maskH, &new_index));
    Result<AEGP_MaskRefH> result;
    result.value = maskH;
    result.error = err;
    return result;
}

Result<void> deleteMask(Result<AEGP_MaskRefH> maskH)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    A_Err err = A_Err_NONE;
    ERR(suites.MaskSuite6()->AEGP_DeleteMaskFromLayer(maskH.value));
    Result<void> result;
    result.error = err;
    return result;
}

Result<bool> getMaskInvert(Result<AEGP_MaskRefH> maskH)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    A_Err err = A_Err_NONE;
    A_Boolean invert = FALSE;
    ERR(suites.MaskSuite6()->AEGP_GetMaskInvert(maskH.value, &invert));
    Result<bool> result;
    result.value = invert != 0;
    result.error = err;
    return result;
}

Result<void> setMaskInvert(Result<AEGP_MaskRefH> maskH, bool invert)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    A_Err err = A_Err_NONE;
    ERR(suites.MaskSuite6()->AEGP_SetMaskInvert(maskH.value, invert ? TRUE : FALSE));
    Result<void> result;
    result.error = err;
    return result;
}

Result<int> getMaskMode(Result<AEGP_MaskRefH> maskH)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    A_Err err = A_Err_NONE;
    PF_MaskMode mode;
    ERR(suites.MaskSuite6()->AEGP_GetMaskMode(maskH.value, &mode));
    Result<int> result;
    result.value = static_cast<int>(mode);
    result.error = err;
    return result;
}

Result<void> setMaskMode(Result<AEGP_MaskRefH> maskH, int mode)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    A_Err err = A_Err_NONE;
    ERR(suites.MaskSuite6()->AEGP_SetMaskMode(maskH.value, static_cast<PF_MaskMode>(mode)));
    Result<void> result;
    result.error = err;
    return result;
}

Result<void> disposeMask(Result<AEGP_MaskRefH> maskH)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    A_Err err = A_Err_NONE;
    ERR(suites.MaskSuite6()->AEGP_DisposeMask(maskH.value));
    Result<void> result;
    result.error = err;
    return result;
}

// ── Mask Outline Suite ──

Result<AEGP_StreamRefH> getNewMaskStream(Result<AEGP_MaskRefH> maskH, int which_stream)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    AEGP_PluginID* pluginIDPtr = SuiteManager::GetInstance().GetPluginID();
    A_Err err = A_Err_NONE;
    AEGP_StreamRefH streamH = NULL;
    ERR(suites.StreamSuite6()->AEGP_GetNewMaskStream(
        *pluginIDPtr, maskH.value, static_cast<AEGP_MaskStream>(which_stream), &streamH));
    Result<AEGP_StreamRefH> result;
    result.value = streamH;
    result.error = err;
    return result;
}

Result<bool> isMaskOutlineOpen(Result<AEGP_MaskOutlineValH> outlineH)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    A_Err err = A_Err_NONE;
    A_Boolean open = FALSE;
    ERR(suites.MaskOutlineSuite3()->AEGP_IsMaskOutlineOpen(outlineH.value, &open));
    Result<bool> result;
    result.value = open != 0;
    result.error = err;
    return result;
}

Result<void> setMaskOutlineOpen(Result<AEGP_MaskOutlineValH> outlineH, bool open)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    A_Err err = A_Err_NONE;
    ERR(suites.MaskOutlineSuite3()->AEGP_SetMaskOutlineOpen(outlineH.value, open ? TRUE : FALSE));
    Result<void> result;
    result.error = err;
    return result;
}

Result<int> getMaskOutlineNumSegments(Result<AEGP_MaskOutlineValH> outlineH)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    A_Err err = A_Err_NONE;
    A_long num = 0;
    ERR(suites.MaskOutlineSuite3()->AEGP_GetMaskOutlineNumSegments(outlineH.value, &num));
    Result<int> result;
    result.value = static_cast<int>(num);
    result.error = err;
    return result;
}

Result<AEGP_MaskVertex> getMaskOutlineVertexInfo(Result<AEGP_MaskOutlineValH> outlineH, int which_point)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    A_Err err = A_Err_NONE;
    AEGP_MaskVertex vertex = {};
    ERR(suites.MaskOutlineSuite3()->AEGP_GetMaskOutlineVertexInfo(outlineH.value,
        static_cast<AEGP_VertexIndex>(which_point), &vertex));
    Result<AEGP_MaskVertex> result;
    result.value = vertex;
    result.error = err;
    return result;
}

Result<void> setMaskOutlineVertexInfo(Result<AEGP_MaskOutlineValH> outlineH, int which_point, const AEGP_MaskVertex* vertexP)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    A_Err err = A_Err_NONE;
    ERR(suites.MaskOutlineSuite3()->AEGP_SetMaskOutlineVertexInfo(outlineH.value,
        static_cast<AEGP_VertexIndex>(which_point), vertexP));
    Result<void> result;
    result.error = err;
    return result;
}

Result<void> createMaskOutlineVertex(Result<AEGP_MaskOutlineValH> outlineH, int position)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    A_Err err = A_Err_NONE;
    AEGP_MaskVertex vertex = {};
    ERR(suites.MaskOutlineSuite3()->AEGP_CreateVertex(outlineH.value,
        static_cast<AEGP_VertexIndex>(position)));
    Result<void> result;
    result.error = err;
    return result;
}

Result<void> deleteMaskOutlineVertex(Result<AEGP_MaskOutlineValH> outlineH, int index)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    A_Err err = A_Err_NONE;
    ERR(suites.MaskOutlineSuite3()->AEGP_DeleteVertex(outlineH.value,
        static_cast<AEGP_VertexIndex>(index)));
    Result<void> result;
    result.error = err;
    return result;
}
