#include "StreamSuites.h"

Result<AEGP_StreamRefH> getNewLayerStream(
    Result<AEGP_LayerH> layerH, AEGP_LayerStream which_stream)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    AEGP_PluginID* pluginIDPtr = SuiteManager::GetInstance().GetPluginID();
    A_Err err = A_Err_NONE;
    AEGP_StreamRefH streamH = NULL;

    ERR(suites.StreamSuite6()->AEGP_GetNewLayerStream(
        *pluginIDPtr, layerH.value, which_stream, &streamH));

    Result<AEGP_StreamRefH> result;
    result.value = streamH;
    result.error = err;
    return result;
}

Result<AEGP_StreamValue2> getNewStreamValue(
    Result<AEGP_StreamRefH> streamH,
    AEGP_LTimeMode time_mode,
    A_Time timeT,
    A_Boolean pre_expression)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    AEGP_PluginID* pluginIDPtr = SuiteManager::GetInstance().GetPluginID();
    A_Err err = A_Err_NONE;
    AEGP_StreamValue2 val = {};

    ERR(suites.StreamSuite6()->AEGP_GetNewStreamValue(
        *pluginIDPtr, streamH.value, time_mode, &timeT, pre_expression, &val));

    Result<AEGP_StreamValue2> result;
    result.value = val;
    result.error = err;
    return result;
}

Result<void> setStreamValue(
    Result<AEGP_StreamRefH> streamH,
    AEGP_StreamValue2* valueP)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    AEGP_PluginID* pluginIDPtr = SuiteManager::GetInstance().GetPluginID();
    A_Err err = A_Err_NONE;

    ERR(suites.StreamSuite6()->AEGP_SetStreamValue(
        *pluginIDPtr, streamH.value, valueP));

    Result<void> result;
    result.error = err;
    return result;
}

Result<AEGP_StreamType> getStreamType(Result<AEGP_StreamRefH> streamH)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    A_Err err = A_Err_NONE;
    AEGP_StreamType type;

    ERR(suites.StreamSuite6()->AEGP_GetStreamType(streamH.value, &type));

    Result<AEGP_StreamType> result;
    result.value = type;
    result.error = err;
    return result;
}

Result<A_Boolean> canVaryOverTime(Result<AEGP_StreamRefH> streamH)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    A_Err err = A_Err_NONE;
    A_Boolean can_vary = FALSE;

    ERR(suites.StreamSuite6()->AEGP_CanVaryOverTime(streamH.value, &can_vary));

    Result<A_Boolean> result;
    result.value = can_vary;
    result.error = err;
    return result;
}

Result<A_Boolean> isStreamTimevarying(Result<AEGP_StreamRefH> streamH)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    A_Err err = A_Err_NONE;
    A_Boolean is_tv = FALSE;

    ERR(suites.StreamSuite6()->AEGP_IsStreamTimevarying(streamH.value, &is_tv));

    Result<A_Boolean> result;
    result.value = is_tv;
    result.error = err;
    return result;
}

Result<void> disposeStream(Result<AEGP_StreamRefH> streamH)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    A_Err err = A_Err_NONE;

    ERR(suites.StreamSuite6()->AEGP_DisposeStream(streamH.value));

    Result<void> result;
    result.error = err;
    return result;
}

Result<void> disposeStreamValue(AEGP_StreamValue2* valueP)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    A_Err err = A_Err_NONE;

    ERR(suites.StreamSuite6()->AEGP_DisposeStreamValue(valueP));

    Result<void> result;
    result.error = err;
    return result;
}

// ── Dynamic Stream ──

Result<int> getNumStreamsInGroup(Result<AEGP_StreamRefH> groupH)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    A_Err err = A_Err_NONE;
    A_long num = 0;

    ERR(suites.DynamicStreamSuite4()->AEGP_GetNumStreamsInGroup(groupH.value, &num));

    Result<int> result;
    result.value = static_cast<int>(num);
    result.error = err;
    return result;
}

Result<AEGP_StreamRefH> getNewStreamByIndex(
    Result<AEGP_StreamRefH> groupH, int index)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    AEGP_PluginID* pluginIDPtr = SuiteManager::GetInstance().GetPluginID();
    A_Err err = A_Err_NONE;
    AEGP_StreamRefH streamH = NULL;

    ERR(suites.DynamicStreamSuite4()->AEGP_GetNewStreamRefByIndex(
        *pluginIDPtr, groupH.value, index, &streamH));

    Result<AEGP_StreamRefH> result;
    result.value = streamH;
    result.error = err;
    return result;
}

Result<AEGP_StreamRefH> getNewStreamByMatchname(
    Result<AEGP_StreamRefH> groupH, const std::string& matchname)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    AEGP_PluginID* pluginIDPtr = SuiteManager::GetInstance().GetPluginID();
    A_Err err = A_Err_NONE;
    AEGP_StreamRefH streamH = NULL;

    ERR(suites.DynamicStreamSuite4()->AEGP_GetNewStreamRefByMatchname(
        *pluginIDPtr, groupH.value, matchname.c_str(), &streamH));

    Result<AEGP_StreamRefH> result;
    result.value = streamH;
    result.error = err;
    return result;
}

// ── Layer Root Stream ──

Result<AEGP_StreamRefH> getNewStreamRefForLayer(Result<AEGP_LayerH> layerH)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    AEGP_PluginID* pluginIDPtr = SuiteManager::GetInstance().GetPluginID();
    A_Err err = A_Err_NONE;
    AEGP_StreamRefH streamH = NULL;

    ERR(suites.DynamicStreamSuite4()->AEGP_GetNewStreamRefForLayer(
        *pluginIDPtr, layerH.value, &streamH));

    Result<AEGP_StreamRefH> result;
    result.value = streamH;
    result.error = err;
    return result;
}

// ── Dynamic Stream Flags ──

Result<AEGP_DynStreamFlags> getDynamicStreamFlags(Result<AEGP_StreamRefH> streamH)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    A_Err err = A_Err_NONE;
    AEGP_DynStreamFlags flags = 0;

    ERR(suites.DynamicStreamSuite4()->AEGP_GetDynamicStreamFlags(streamH.value, &flags));

    Result<AEGP_DynStreamFlags> result;
    result.value = flags;
    result.error = err;
    return result;
}

Result<void> setDynamicStreamFlag(
    Result<AEGP_StreamRefH> streamH, AEGP_DynStreamFlags one_flag,
    A_Boolean undoableB, A_Boolean setB)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    A_Err err = A_Err_NONE;

    ERR(suites.DynamicStreamSuite4()->AEGP_SetDynamicStreamFlag(
        streamH.value, one_flag, undoableB, setB));

    Result<void> result;
    result.error = err;
    return result;
}
