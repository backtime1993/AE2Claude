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

Result<A_Boolean> isStreamLegal(
    Result<AEGP_LayerH> layerH, AEGP_LayerStream which_stream)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    A_Err err = A_Err_NONE;
    A_Boolean isLegal = FALSE;

    ERR(suites.StreamSuite6()->AEGP_IsStreamLegal(
        layerH.value, which_stream, &isLegal));

    Result<A_Boolean> result;
    result.value = isLegal;
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

Result<AEGP_StreamGroupingType> getStreamGroupingType(Result<AEGP_StreamRefH> streamH)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    A_Err err = A_Err_NONE;
    AEGP_StreamGroupingType groupType = AEGP_StreamGroupingType_NONE;

    ERR(suites.DynamicStreamSuite4()->AEGP_GetStreamGroupingType(streamH.value, &groupType));

    Result<AEGP_StreamGroupingType> result;
    result.value = groupType;
    result.error = err;
    return result;
}

Result<std::string> getStreamName(Result<AEGP_StreamRefH> streamH, bool forceEnglish)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    A_Err err = A_Err_NONE;
    AEGP_MemHandle utfStreamNameMH = NULL;
    A_UTF16Char* utfStreamNameP = NULL;
    std::string streamName;

    PT_XTE_START {
        AEGP_PluginID* pluginIDPtr = SuiteManager::GetInstance().GetPluginID();
        if (!pluginIDPtr) {
            throw A_Err_STRUCT;
        }

        PT_ETX(suites.StreamSuite6()->AEGP_GetStreamName(
            *pluginIDPtr,
            streamH.value,
            forceEnglish ? TRUE : FALSE,
            &utfStreamNameMH));

        if (utfStreamNameMH) {
            PT_ETX(suites.MemorySuite1()->AEGP_LockMemHandle(utfStreamNameMH, (void**)&utfStreamNameP));
            streamName = convertUTF16ToUTF8(utfStreamNameP);
            PT_ETX(suites.MemorySuite1()->AEGP_UnlockMemHandle(utfStreamNameMH));
            PT_ETX(suites.MemorySuite1()->AEGP_FreeMemHandle(utfStreamNameMH));
            utfStreamNameMH = NULL;
        }

        Result<std::string> result;
        result.value = streamName;
        result.error = err;
        return result;
    }
    PT_XTE_CATCH_RETURN_ERR;
}

Result<std::string> getStreamMatchName(Result<AEGP_StreamRefH> streamH)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    A_Err err = A_Err_NONE;
    A_char matchName[AEGP_MAX_STREAM_MATCH_NAME_SIZE] = {};

    ERR(suites.DynamicStreamSuite4()->AEGP_GetMatchName(streamH.value, matchName));

    Result<std::string> result;
    result.value = std::string(matchName);
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
    Result<AEGP_StreamRefH> result;
    result.value = NULL;

    if (groupH.error != A_Err_NONE) {
        result.error = groupH.error;
        return result;
    }
    if (groupH.value == NULL || pluginIDPtr == NULL) {
        result.error = A_Err_STRUCT;
        return result;
    }

    AEGP_StreamGroupingType groupType = AEGP_StreamGroupingType_NONE;
    A_Err err = suites.DynamicStreamSuite4()->AEGP_GetStreamGroupingType(
        groupH.value, &groupType);
    if (err != A_Err_NONE) {
        result.error = err;
        return result;
    }

    if (groupType != AEGP_StreamGroupingType_NAMED_GROUP &&
        groupType != AEGP_StreamGroupingType_INDEXED_GROUP) {
        result.error = A_Err_GENERIC;
        return result;
    }

    A_long numStreams = 0;
    err = suites.DynamicStreamSuite4()->AEGP_GetNumStreamsInGroup(
        groupH.value, &numStreams);
    if (err != A_Err_NONE) {
        result.error = err;
        return result;
    }

    for (A_long index = 0; index < numStreams; ++index) {
        AEGP_StreamRefH candidateH = NULL;
        err = suites.DynamicStreamSuite4()->AEGP_GetNewStreamRefByIndex(
            *pluginIDPtr, groupH.value, index, &candidateH);
        if (err != A_Err_NONE) {
            result.error = err;
            return result;
        }
        if (candidateH == NULL) {
            continue;
        }

        A_char candidateMatchName[AEGP_MAX_STREAM_MATCH_NAME_SIZE] = {};
        err = suites.DynamicStreamSuite4()->AEGP_GetMatchName(
            candidateH, candidateMatchName);
        if (err == A_Err_NONE && matchname == candidateMatchName) {
            result.value = candidateH;
            result.error = A_Err_NONE;
            return result;
        }

        A_Err disposeErr = suites.StreamSuite6()->AEGP_DisposeStream(candidateH);
        if (err != A_Err_NONE) {
            result.error = err;
            return result;
        }
        if (disposeErr != A_Err_NONE) {
            result.error = disposeErr;
            return result;
        }
    }

    result.error = A_Err_GENERIC;
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
