#pragma once
#include "Core.h"

Result<int> getStreamNumKFs(Result<AEGP_StreamRefH> streamH);

Result<A_Time> getKeyframeTime(
    Result<AEGP_StreamRefH> streamH, int kf_index, AEGP_LTimeMode time_mode);

Result<int> insertKeyframe(
    Result<AEGP_StreamRefH> streamH, AEGP_LTimeMode time_mode, A_Time timeT);

Result<void> setKeyframeValue(
    Result<AEGP_StreamRefH> streamH, int kf_index, AEGP_StreamValue2* valueP);

Result<AEGP_StreamValue2> getKeyframeValue(
    Result<AEGP_StreamRefH> streamH, int kf_index);

Result<void> deleteKeyframe(Result<AEGP_StreamRefH> streamH, int kf_index);

Result<void> setKeyframeInterpolation(
    Result<AEGP_StreamRefH> streamH, int kf_index,
    AEGP_KeyframeInterpolationType in_type,
    AEGP_KeyframeInterpolationType out_type);

Result<void> setKeyframeTemporalEase(
    Result<AEGP_StreamRefH> streamH, int kf_index, A_long num_dims,
    AEGP_KeyframeEase* in_ease, AEGP_KeyframeEase* out_ease);

Result<void> setKeyframeSpatialTangents(
    Result<AEGP_StreamRefH> streamH, int kf_index,
    const AEGP_StreamValue2* in_tangent, const AEGP_StreamValue2* out_tangent);

Result<std::string> getExpression(Result<AEGP_StreamRefH> streamH);
Result<void> setExpression(Result<AEGP_StreamRefH> streamH, const std::string& expr);
