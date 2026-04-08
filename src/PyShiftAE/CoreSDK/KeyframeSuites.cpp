#include "KeyframeSuites.h"

Result<int> getStreamNumKFs(Result<AEGP_StreamRefH> streamH)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    A_Err err = A_Err_NONE;
    A_long num = 0;

    ERR(suites.KeyframeSuite5()->AEGP_GetStreamNumKFs(streamH.value, &num));

    Result<int> result;
    result.value = static_cast<int>(num);
    result.error = err;
    return result;
}

Result<A_Time> getKeyframeTime(
    Result<AEGP_StreamRefH> streamH, int kf_index, AEGP_LTimeMode time_mode)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    A_Err err = A_Err_NONE;
    A_Time timeT = {};

    ERR(suites.KeyframeSuite5()->AEGP_GetKeyframeTime(
        streamH.value, static_cast<AEGP_KeyframeIndex>(kf_index), time_mode, &timeT));

    Result<A_Time> result;
    result.value = timeT;
    result.error = err;
    return result;
}

Result<int> insertKeyframe(
    Result<AEGP_StreamRefH> streamH, AEGP_LTimeMode time_mode, A_Time timeT)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    A_Err err = A_Err_NONE;
    AEGP_KeyframeIndex new_index = 0;

    ERR(suites.KeyframeSuite5()->AEGP_InsertKeyframe(
        streamH.value, time_mode, &timeT, &new_index));

    Result<int> result;
    result.value = static_cast<int>(new_index);
    result.error = err;
    return result;
}

Result<void> setKeyframeValue(
    Result<AEGP_StreamRefH> streamH, int kf_index, AEGP_StreamValue2* valueP)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    A_Err err = A_Err_NONE;

    ERR(suites.KeyframeSuite5()->AEGP_SetKeyframeValue(
        streamH.value, static_cast<AEGP_KeyframeIndex>(kf_index), valueP));

    Result<void> result;
    result.error = err;
    return result;
}

Result<AEGP_StreamValue2> getKeyframeValue(
    Result<AEGP_StreamRefH> streamH, int kf_index)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    A_Err err = A_Err_NONE;
    AEGP_StreamValue2 val = {};

    ERR(suites.KeyframeSuite5()->AEGP_GetNewKeyframeValue(
        *SuiteManager::GetInstance().GetPluginID(),
        streamH.value, static_cast<AEGP_KeyframeIndex>(kf_index), &val));

    Result<AEGP_StreamValue2> result;
    result.value = val;
    result.error = err;
    return result;
}

Result<void> deleteKeyframe(Result<AEGP_StreamRefH> streamH, int kf_index)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    A_Err err = A_Err_NONE;

    ERR(suites.KeyframeSuite5()->AEGP_DeleteKeyframe(
        streamH.value, static_cast<AEGP_KeyframeIndex>(kf_index)));

    Result<void> result;
    result.error = err;
    return result;
}

Result<void> setKeyframeInterpolation(
    Result<AEGP_StreamRefH> streamH, int kf_index,
    AEGP_KeyframeInterpolationType in_type,
    AEGP_KeyframeInterpolationType out_type)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    A_Err err = A_Err_NONE;

    ERR(suites.KeyframeSuite5()->AEGP_SetKeyframeInterpolation(
        streamH.value, static_cast<AEGP_KeyframeIndex>(kf_index), in_type, out_type));

    Result<void> result;
    result.error = err;
    return result;
}

Result<void> setKeyframeTemporalEase(
    Result<AEGP_StreamRefH> streamH, int kf_index, A_long num_dims,
    AEGP_KeyframeEase* in_ease, AEGP_KeyframeEase* out_ease)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    A_Err err = A_Err_NONE;

    ERR(suites.KeyframeSuite5()->AEGP_SetKeyframeTemporalEase(
        streamH.value, static_cast<AEGP_KeyframeIndex>(kf_index),
        num_dims, in_ease, out_ease));

    Result<void> result;
    result.error = err;
    return result;
}

Result<void> setKeyframeSpatialTangents(
    Result<AEGP_StreamRefH> streamH, int kf_index,
    const AEGP_StreamValue2* in_tangent, const AEGP_StreamValue2* out_tangent)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    A_Err err = A_Err_NONE;

    ERR(suites.KeyframeSuite5()->AEGP_SetKeyframeSpatialTangents(
        streamH.value, static_cast<AEGP_KeyframeIndex>(kf_index),
        in_tangent, out_tangent));

    Result<void> result;
    result.error = err;
    return result;
}

Result<std::string> getExpression(Result<AEGP_StreamRefH> streamH)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    AEGP_PluginID* pluginIDPtr = SuiteManager::GetInstance().GetPluginID();
    A_Err err = A_Err_NONE;
    AEGP_MemHandle expressionHZ = NULL;

    ERR(suites.StreamSuite6()->AEGP_GetExpression(
        *pluginIDPtr, streamH.value, &expressionHZ));

    std::string expr;
    if (expressionHZ) {
        A_UTF16Char* exprP = NULL;
        ERR(suites.MemorySuite1()->AEGP_LockMemHandle(expressionHZ, (void**)&exprP));
        if (exprP) {
            expr = convertUTF16ToUTF8(exprP);
        }
        ERR(suites.MemorySuite1()->AEGP_UnlockMemHandle(expressionHZ));
        ERR(suites.MemorySuite1()->AEGP_FreeMemHandle(expressionHZ));
    }

    Result<std::string> result;
    result.value = expr;
    result.error = err;
    return result;
}

Result<void> setExpression(Result<AEGP_StreamRefH> streamH, const std::string& expr)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    A_Err err = A_Err_NONE;

    auto utf16 = convertUTF8ToUTF16(expr);
    ERR(suites.StreamSuite6()->AEGP_SetExpression(
        *SuiteManager::GetInstance().GetPluginID(),
        streamH.value, utf16.data()));

    Result<void> result;
    result.error = err;
    return result;
}
