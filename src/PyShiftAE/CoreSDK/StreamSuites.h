#pragma once
#include "Core.h"

// ── Layer Stream ──
Result<AEGP_StreamRefH> getNewLayerStream(
    Result<AEGP_LayerH> layerH, AEGP_LayerStream which_stream);
Result<A_Boolean> isStreamLegal(
    Result<AEGP_LayerH> layerH, AEGP_LayerStream which_stream);

// ── Stream Value ──
Result<AEGP_StreamValue2> getNewStreamValue(
    Result<AEGP_StreamRefH> streamH,
    AEGP_LTimeMode time_mode,
    A_Time timeT,
    A_Boolean pre_expression);

Result<void> setStreamValue(
    Result<AEGP_StreamRefH> streamH,
    AEGP_StreamValue2* valueP);

// ── Stream Metadata ──
Result<AEGP_StreamType> getStreamType(Result<AEGP_StreamRefH> streamH);
Result<A_Boolean> canVaryOverTime(Result<AEGP_StreamRefH> streamH);
Result<A_Boolean> isStreamTimevarying(Result<AEGP_StreamRefH> streamH);
Result<AEGP_StreamGroupingType> getStreamGroupingType(Result<AEGP_StreamRefH> streamH);
Result<std::string> getStreamName(Result<AEGP_StreamRefH> streamH, bool forceEnglish = false);
Result<std::string> getStreamMatchName(Result<AEGP_StreamRefH> streamH);

// ── Dispose ──
Result<void> disposeStream(Result<AEGP_StreamRefH> streamH);
Result<void> disposeStreamValue(AEGP_StreamValue2* valueP);

// ── Dynamic Stream ──
Result<int> getNumStreamsInGroup(Result<AEGP_StreamRefH> groupH);
Result<AEGP_StreamRefH> getNewStreamByIndex(
    Result<AEGP_StreamRefH> groupH, int index);
Result<AEGP_StreamRefH> getNewStreamByMatchname(
    Result<AEGP_StreamRefH> groupH, const std::string& matchname);

// ── Layer Root Stream ──
Result<AEGP_StreamRefH> getNewStreamRefForLayer(Result<AEGP_LayerH> layerH);

// ── Dynamic Stream Flags ──
Result<AEGP_DynStreamFlags> getDynamicStreamFlags(Result<AEGP_StreamRefH> streamH);
Result<void> setDynamicStreamFlag(
    Result<AEGP_StreamRefH> streamH, AEGP_DynStreamFlags one_flag,
    A_Boolean undoableB, A_Boolean setB);
