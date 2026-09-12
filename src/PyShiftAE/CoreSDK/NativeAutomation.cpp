#include "NativeAutomation.h"
#include "NativeAutomationValidation.h"
#include "Core.h"
#include "TaskUtils.h"
#include <pybind11/stl.h>
#include <array>
#include <variant>

namespace py = pybind11;
using namespace pybind11::literals;

namespace {
using Path = std::vector<std::variant<int, std::string>>;
using Value = std::variant<double, std::vector<double>>;
using NativeAutomation::timeFromSeconds;

void check(A_Err error, const char* operation) {
    if (error != A_Err_NONE)
        throw std::runtime_error(std::string(operation) + ":sdk_error=" + std::to_string(error));
}

struct Sdk {
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    AEGP_PluginID plugin = *SuiteManager::GetInstance().GetPluginID();
    AEGP_ProjSuite6* projects = suites.ProjSuite6();
    AEGP_ItemSuite9* items = suites.ItemSuite9();
    AEGP_CompSuite11* comps = suites.CompSuite11();
    AEGP_LayerSuite9* layers = suites.LayerSuite9();
    AEGP_StreamSuite6* streams = suites.StreamSuite6();
    AEGP_DynamicStreamSuite4* dynamic = suites.DynamicStreamSuite4();
    AEGP_KeyframeSuite5* keys = suites.KeyframeSuite5();
};

// All SDK handles live inside one main-thread dispatch, including their cleanup.
struct Memory {
    Sdk& sdk;
    AEGP_MemHandle handle = nullptr;
    bool locked = false;
    explicit Memory(Sdk& s) : sdk(s) {}
    ~Memory() {
        if (handle) {
            if (locked) sdk.suites.MemorySuite1()->AEGP_UnlockMemHandle(handle);
            sdk.suites.MemorySuite1()->AEGP_FreeMemHandle(handle);
        }
    }
    std::string text() {
        if (!handle) return {};
        void* data = nullptr;
        check(sdk.suites.MemorySuite1()->AEGP_LockMemHandle(handle, &data), "lock_utf16");
        locked = true;
        return data ? convertUTF16ToUTF8(static_cast<A_UTF16Char*>(data)) : "";
    }
};

struct Stream {
    Sdk& sdk;
    std::vector<AEGP_StreamRefH> handles;
    explicit Stream(Sdk& s) : sdk(s) { handles.reserve(65); }
    ~Stream() {
        for (auto it = handles.rbegin(); it != handles.rend(); ++it)
            sdk.streams->AEGP_DisposeStream(*it);
    }
    AEGP_StreamRefH get() const { return handles.back(); }
    void resolve(AEGP_LayerH layer, const Path& path) {
        AEGP_StreamRefH h = nullptr;
        check(sdk.dynamic->AEGP_GetNewStreamRefForLayer(sdk.plugin, layer, &h), "layer_stream");
        if (!h) throw std::runtime_error("layer_stream:null");
        handles.push_back(h);
        for (const auto& step : path) {
            h = nullptr;
            A_Err err = std::holds_alternative<int>(step)
                ? sdk.dynamic->AEGP_GetNewStreamRefByIndex(sdk.plugin, get(), std::get<int>(step), &h)
                : sdk.dynamic->AEGP_GetNewStreamRefByMatchname(sdk.plugin, get(), std::get<std::string>(step).c_str(), &h);
            if (h) handles.push_back(h);
            check(err, "property_path");
            if (!h) throw std::runtime_error("property_path:not_found");
        }
    }
};

struct OwnedValue {
    Sdk& sdk;
    AEGP_StreamValue2 value{};
    bool owned = false;
    explicit OwnedValue(Sdk& s) : sdk(s) {}
    ~OwnedValue() { if (owned) sdk.streams->AEGP_DisposeStreamValue(&value); }
};

AEGP_ProjectH project(Sdk& sdk) {
    AEGP_ProjectH result = nullptr;
    check(sdk.projects->AEGP_GetProjectByIndex(0, &result), "project");
    if (!result) throw std::runtime_error("no_project");
    return result;
}

int itemId(Sdk& sdk, AEGP_ItemH item) {
    A_long id = 0;
    if (item) check(sdk.items->AEGP_GetItemID(item, &id), "item_id");
    return static_cast<int>(id);
}

int layerId(Sdk& sdk, AEGP_LayerH layer) {
    AEGP_LayerIDVal id = 0;
    if (layer) check(sdk.layers->AEGP_GetLayerID(layer, &id), "layer_id");
    return static_cast<int>(id);
}

AEGP_CompH composition(Sdk& sdk, int id, bool optional = false) {
    AEGP_CompH result = nullptr;
    if (!id) {
        check(sdk.comps->AEGP_GetMostRecentlyUsedComp(&result), "recent_comp");
    } else {
        const auto proj = project(sdk);
        AEGP_ItemH item = nullptr;
        check(sdk.items->AEGP_GetFirstProjItem(proj, &item), "first_item");
        int scanned = 0;
        while (item) {
            if (++scanned > 100000) throw std::runtime_error("composition_lookup_limit");
            if (itemId(sdk, item) == id) {
                AEGP_ItemType type{};
                check(sdk.items->AEGP_GetItemType(item, &type), "item_type");
                if (type != AEGP_ItemType_COMP) throw std::runtime_error("item_is_not_composition");
                check(sdk.comps->AEGP_GetCompFromItem(item, &result), "composition");
                break;
            }
            AEGP_ItemH next = nullptr;
            check(sdk.items->AEGP_GetNextProjItem(proj, item, &next), "next_item");
            item = next;
        }
    }
    if (!result && (!optional || id)) throw std::runtime_error("composition_not_found");
    return result;
}

int compId(Sdk& sdk, AEGP_CompH comp) {
    AEGP_ItemH item = nullptr;
    check(sdk.comps->AEGP_GetItemFromComp(comp, &item), "comp_item");
    return itemId(sdk, item);
}

AEGP_LayerH findLayer(Sdk& sdk, AEGP_CompH comp, int id) {
    AEGP_LayerH layer = nullptr;
    check(sdk.layers->AEGP_GetLayerFromLayerID(comp, id, &layer), "layer_lookup");
    if (!layer) throw std::runtime_error("layer_not_found_in_composition");
    return layer;
}

A_Time nativeTime(double seconds) {
    const auto time = timeFromSeconds(seconds);
    return {time.value, time.scale};
}
double seconds(const A_Time& time) {
    return time.scale ? static_cast<double>(time.value) / time.scale : 0.0;
}

Path parsePath(const py::list& path) {
    if (path.empty() || path.size() > 64) throw std::invalid_argument("path must have 1..64 steps");
    Path output;
    for (auto step : path) {
        if (py::isinstance<py::bool_>(step)) throw std::invalid_argument("boolean path index");
        if (py::isinstance<py::int_>(step)) {
            const auto index = step.cast<int>();
            if (index < 0) throw std::invalid_argument("path indices are zero-based");
            output.emplace_back(index);
        } else if (py::isinstance<py::str>(step)) {
            auto name = step.cast<std::string>();
            if (name.empty() || name.size() > 255 || name.find('\0') != std::string::npos)
                throw std::invalid_argument("invalid matchName");
            output.emplace_back(std::move(name));
        } else throw std::invalid_argument("path requires matchNames or zero-based indices");
    }
    return output;
}

void ids(int comp, int layer = 1) {
    if (comp < 0 || layer <= 0) throw std::invalid_argument("invalid stable composition/layer ID");
}
void limit(int n, int maximum) {
    if (n < 1 || n > maximum) throw std::invalid_argument("limit outside supported range");
}
void times(const std::vector<double>& values, int maximum) {
    limit(static_cast<int>(values.size()), maximum);
    for (double t : values) timeFromSeconds(t);
}

int dimensions(AEGP_StreamType type) {
    switch (type) {
    case AEGP_StreamType_OneD: return 1;
    case AEGP_StreamType_TwoD: case AEGP_StreamType_TwoD_SPATIAL: return 2;
    case AEGP_StreamType_ThreeD: case AEGP_StreamType_ThreeD_SPATIAL: return 3;
    case AEGP_StreamType_COLOR: return 4;
    default: throw std::runtime_error("unsupported_stream_type:" + std::to_string(type));
    }
}

Value unpack(AEGP_StreamType type, const AEGP_StreamValue2& value) {
    switch (type) {
    case AEGP_StreamType_OneD: return value.val.one_d;
    case AEGP_StreamType_TwoD: case AEGP_StreamType_TwoD_SPATIAL:
        return std::vector<double>{value.val.two_d.x, value.val.two_d.y};
    case AEGP_StreamType_ThreeD: case AEGP_StreamType_ThreeD_SPATIAL:
        return std::vector<double>{value.val.three_d.x, value.val.three_d.y, value.val.three_d.z};
    case AEGP_StreamType_COLOR:
        return std::vector<double>{value.val.color.redF, value.val.color.greenF, value.val.color.blueF, value.val.color.alphaF};
    default: throw std::runtime_error("unsupported_stream_type");
    }
}

AEGP_StreamValue2 pack(AEGP_StreamRefH stream, AEGP_StreamType type, const Value& input) {
    AEGP_StreamValue2 result{};
    result.streamH = stream;
    const int dim = dimensions(type);
    if (dim == 1) {
        if (!std::holds_alternative<double>(input)) throw std::invalid_argument("expected_scalar");
        result.val.one_d = std::get<double>(input);
    } else {
        if (!std::holds_alternative<std::vector<double>>(input)) throw std::invalid_argument("expected_vector");
        const auto& v = std::get<std::vector<double>>(input);
        if (v.size() != static_cast<std::size_t>(dim)) throw std::invalid_argument("value_dimension_mismatch");
        if (type == AEGP_StreamType_COLOR) {
            result.val.color.redF = v[0]; result.val.color.greenF = v[1];
            result.val.color.blueF = v[2]; result.val.color.alphaF = v[3];
        } else if (dim == 2) { result.val.two_d.x = v[0]; result.val.two_d.y = v[1]; }
        else { result.val.three_d.x = v[0]; result.val.three_d.y = v[1]; result.val.three_d.z = v[2]; }
    }
    return result;
}

template<typename F> auto dispatch(F function) {
    // Parse Python input before releasing the GIL; only plain C++ data crosses
    // the queue. Convert the result to Python after reacquiring the GIL.
    py::gil_scoped_release release;
    auto message = enqueueSyncTask(std::move(function));
    message->wait();
    return message->getResult();
}

py::dict base() {
    return py::dict("ok"_a=true, "backend"_a="aegp-native", "revision"_a=NativeAutomation::kRevision, "dispatches"_a=1);
}

struct ItemRow { int id=0, parent=0, type=0, flags=0, width=0, height=0; double duration=0; std::string name; };
struct LayerRow { int id=0, index=0, source=0, parent=0, flags=0, effects=0; double in=0, duration=0, offset=0; std::string name; };
struct Snapshot {
    std::string path; bool dirty=false, itemsTruncated=false, layersTruncated=false;
    int comp=0, layerCount=0; double fps=0, time=0;
    std::vector<ItemRow> items; std::vector<LayerRow> layers;
};

Snapshot snapshot(int requestedComp, int maxItems, int maxLayers) {
    Sdk sdk;
    Snapshot result;
    auto proj = project(sdk);
    Memory path(sdk);
    check(sdk.projects->AEGP_GetProjectPath(proj, &path.handle), "project_path");
    result.path = path.text();
    A_Boolean dirty = FALSE;
    check(sdk.projects->AEGP_ProjectIsDirty(proj, &dirty), "project_dirty");
    result.dirty = dirty != FALSE;
    AEGP_ItemH item = nullptr;
    check(sdk.items->AEGP_GetFirstProjItem(proj, &item), "first_item");
    while (item && static_cast<int>(result.items.size()) < maxItems) {
        ItemRow row;
        row.id = itemId(sdk, item);
        Memory name(sdk);
        check(sdk.items->AEGP_GetItemName(sdk.plugin, item, &name.handle), "item_name");
        row.name = name.text();
        AEGP_ItemType type{}; AEGP_ItemFlags flags{}; AEGP_ItemH parent=nullptr;
        check(sdk.items->AEGP_GetItemType(item, &type), "item_type");
        check(sdk.items->AEGP_GetItemFlags(item, &flags), "item_flags");
        check(sdk.items->AEGP_GetItemParentFolder(item, &parent), "item_parent");
        row.type = type; row.flags = flags; row.parent = itemId(sdk, parent);
        if (type != AEGP_ItemType_FOLDER) {
            A_long w=0,h=0; A_Time duration{};
            check(sdk.items->AEGP_GetItemDimensions(item,&w,&h), "item_dimensions");
            check(sdk.items->AEGP_GetItemDuration(item,&duration), "item_duration");
            row.width=w; row.height=h; row.duration=seconds(duration);
        }
        result.items.push_back(std::move(row));
        AEGP_ItemH next=nullptr;
        check(sdk.items->AEGP_GetNextProjItem(proj,item,&next), "next_item");
        item=next;
    }
    result.itemsTruncated = item != nullptr;
    const auto comp = composition(sdk, requestedComp, true);
    if (!comp) return result;
    result.comp = compId(sdk, comp);
    check(sdk.comps->AEGP_GetCompFramerate(comp,&result.fps), "comp_fps");
    AEGP_ItemH compItem=nullptr; A_Time current{}; A_long count=0;
    check(sdk.comps->AEGP_GetItemFromComp(comp,&compItem), "comp_item");
    check(sdk.items->AEGP_GetItemCurrentTime(compItem,&current), "comp_time");
    check(sdk.layers->AEGP_GetCompNumLayers(comp,&count), "layer_count");
    result.time=seconds(current); result.layerCount=count; result.layersTruncated=count>maxLayers;
    for (A_long i=0; i<count && i<maxLayers; ++i) {
        AEGP_LayerH layer=nullptr, parent=nullptr; AEGP_ItemH source=nullptr;
        check(sdk.layers->AEGP_GetCompLayerByIndex(comp,i,&layer), "comp_layer");
        LayerRow row; row.id=layerId(sdk,layer); row.index=static_cast<int>(i)+1;
        Memory name(sdk), sourceName(sdk);
        check(sdk.layers->AEGP_GetLayerName(sdk.plugin,layer,&name.handle,&sourceName.handle), "layer_name");
        row.name=name.text();
        if (row.name.empty()) row.name=sourceName.text();
        check(sdk.layers->AEGP_GetLayerParent(layer,&parent), "layer_parent");
        check(sdk.layers->AEGP_GetLayerSourceItem(layer,&source), "layer_source");
        row.parent=layerId(sdk,parent); row.source=itemId(sdk,source);
        AEGP_LayerFlags flags{}; A_Time in{},duration{},offset{}; A_long effects=0;
        check(sdk.layers->AEGP_GetLayerFlags(layer,&flags), "layer_flags");
        check(sdk.layers->AEGP_GetLayerInPoint(layer,AEGP_LTimeMode_CompTime,&in), "layer_in");
        check(sdk.layers->AEGP_GetLayerDuration(layer,AEGP_LTimeMode_CompTime,&duration), "layer_duration");
        check(sdk.layers->AEGP_GetLayerOffset(layer,&offset), "layer_offset");
        check(sdk.suites.EffectSuite4()->AEGP_GetLayerNumEffects(layer,&effects), "layer_effects");
        row.flags=flags; row.effects=effects; row.in=seconds(in); row.duration=seconds(duration); row.offset=seconds(offset);
        result.layers.push_back(std::move(row));
    }
    return result;
}

struct Sample { int comp=0, type=0, keyCount=0; bool expression=false; std::vector<Value> values; };
Sample sample(int compID, int layerID, const Path& path, const std::vector<double>& samples, bool preExpression) {
    Sdk sdk; Sample result;
    auto comp=composition(sdk,compID); result.comp=compId(sdk,comp);
    Stream stream(sdk); stream.resolve(findLayer(sdk,comp,layerID),path);
    AEGP_StreamType type{}; A_long count=0; A_Boolean expression=FALSE;
    check(sdk.streams->AEGP_GetStreamType(stream.get(),&type), "stream_type"); dimensions(type);
    check(sdk.keys->AEGP_GetStreamNumKFs(stream.get(),&count), "keyframe_count");
    check(sdk.streams->AEGP_GetExpressionState(sdk.plugin,stream.get(),&expression), "expression_state");
    result.type=type; result.keyCount=count; result.expression=expression!=FALSE;
    result.values.reserve(samples.size());
    for (double t : samples) {
        auto time=nativeTime(t); OwnedValue value(sdk);
        check(sdk.streams->AEGP_GetNewStreamValue(sdk.plugin,stream.get(),AEGP_LTimeMode_CompTime,&time,preExpression,&value.value), "sample_value");
        value.owned=true; result.values.push_back(unpack(type,value.value));
    }
    return result;
}

struct Key { A_Time time{}; Value value; int index=0, in=0, out=0, flags=0; std::vector<std::array<double,4>> ease; };
struct Keys { int comp=0, type=0, total=0; std::vector<Key> rows; };
Keys readKeys(int compID,int layerID,const Path& path,int start,int maximum) {
    Sdk sdk; Keys result;
    auto comp=composition(sdk,compID); result.comp=compId(sdk,comp);
    Stream stream(sdk); stream.resolve(findLayer(sdk,comp,layerID),path);
    AEGP_StreamType type{}; A_long count=0; A_short dims=0;
    check(sdk.streams->AEGP_GetStreamType(stream.get(),&type), "stream_type"); dimensions(type);
    check(sdk.keys->AEGP_GetStreamNumKFs(stream.get(),&count), "keyframe_count");
    check(sdk.keys->AEGP_GetStreamTemporalDimensionality(stream.get(),&dims), "temporal_dimensions");
    result.type=type; result.total=count;
    for (A_long i=start; i<count && i-start<maximum; ++i) {
        Key row; row.index=i;
        OwnedValue value(sdk);
        check(sdk.keys->AEGP_GetKeyframeTime(stream.get(),i,AEGP_LTimeMode_CompTime,&row.time), "keyframe_time");
        check(sdk.keys->AEGP_GetNewKeyframeValue(sdk.plugin,stream.get(),i,&value.value), "keyframe_value");
        value.owned=true; row.value=unpack(type,value.value);
        AEGP_KeyframeInterpolationType in{},out{}; AEGP_KeyframeFlags flags{};
        check(sdk.keys->AEGP_GetKeyframeInterpolation(stream.get(),i,&in,&out), "keyframe_interpolation");
        check(sdk.keys->AEGP_GetKeyframeFlags(stream.get(),i,&flags), "keyframe_flags");
        row.in=in; row.out=out; row.flags=flags;
        for (A_short d=0;d<dims;++d) {
            AEGP_KeyframeEase inEase{},outEase{};
            check(sdk.keys->AEGP_GetKeyframeTemporalEase(stream.get(),i,d,&inEase,&outEase), "keyframe_ease");
            row.ease.push_back({inEase.speedF,inEase.influenceF,outEase.speedF,outEase.influenceF});
        }
        result.rows.push_back(std::move(row));
    }
    return result;
}

struct Frame { double time; Value value; };
struct WriteResult { int comp=0, written=0; bool ok=true; std::string error, outcome="not_started"; };
WriteResult writeKeys(int compID,int layerID,const Path& path,const std::vector<Frame>& frames,bool dryRun,const std::string& undoName) {
    WriteResult result;
    Sdk sdk;
    auto comp=composition(sdk,compID); result.comp=compId(sdk,comp);
    auto layer=findLayer(sdk,comp,layerID);
    AEGP_LayerFlags flags{};
    check(sdk.layers->AEGP_GetLayerFlags(layer,&flags), "layer_flags");
    if (flags & AEGP_LayerFlag_LOCKED) throw std::runtime_error("layer_is_locked; outcome=not_started");
    Stream stream(sdk); stream.resolve(layer,path);
    AEGP_StreamType type{}; A_Boolean canVary=FALSE;
    check(sdk.streams->AEGP_GetStreamType(stream.get(),&type), "stream_type");
    check(sdk.streams->AEGP_CanVaryOverTime(stream.get(),&canVary), "stream_can_vary");
    if (!canVary) throw std::runtime_error("stream_cannot_vary; outcome=not_started");
    std::vector<AEGP_StreamValue2> values; values.reserve(frames.size());
    std::vector<A_Time> timeValues; timeValues.reserve(frames.size());
    for (const auto& frame : frames) {
        values.push_back(pack(stream.get(),type,frame.value));
        timeValues.push_back(nativeTime(frame.time));
    }
    if (dryRun) return result;
    check(sdk.suites.UtilitySuite6()->AEGP_StartUndoGroup(undoName.c_str()), "start_undo");
    struct Undo { Sdk& sdk; bool open=true; ~Undo() { if(open) sdk.suites.UtilitySuite6()->AEGP_EndUndoGroup(); } } undo{sdk};
    AEGP_AddKeyframesInfoH batch=nullptr;
    try {
        check(sdk.keys->AEGP_StartAddKeyframes(stream.get(),&batch), "start_add_keys");
        if (!batch) throw std::runtime_error("start_add_keys:null_handle");
        for (std::size_t i=0; i<frames.size(); ++i) {
            A_long index=-1;
            check(sdk.keys->AEGP_AddKeyframes(batch,AEGP_LTimeMode_CompTime,&timeValues[i],&index), "add_key");
            check(sdk.keys->AEGP_SetAddKeyframe(batch,index,&values[i]), "set_add_key");
        }
        auto owned=batch; batch=nullptr; // End consumes the opaque handle.
        check(sdk.keys->AEGP_EndAddKeyframes(TRUE,owned), "commit_keys");
        result.written=static_cast<int>(frames.size()); result.outcome="completed";
    } catch (const std::exception& error) {
        result.ok=false; result.error=error.what();
        if (batch && sdk.keys->AEGP_EndAddKeyframes(FALSE,batch)!=A_Err_NONE)
            result.error+=";abort_keys_failed";
        // The SDK does not promise transaction rollback for every host failure.
        // Do not advertise automatic retry even when abort cleanup succeeds.
        result.outcome="unknown";
    }
    undo.open=false;
    const auto undoError=sdk.suites.UtilitySuite6()->AEGP_EndUndoGroup();
    if (undoError!=A_Err_NONE) { result.ok=false; result.error+=";end_undo_failed"; result.outcome="unknown"; }
    return result;
}

struct MatrixRow { int layer; double time; std::array<std::array<double,4>,4> matrix; };
struct Matrices { int comp=0; std::vector<MatrixRow> rows; };
Matrices transforms(int compID,const std::vector<int>& layerIDs,const std::vector<double>& samples) {
    Sdk sdk; Matrices result;
    auto comp=composition(sdk,compID); result.comp=compId(sdk,comp);
    for (int id : layerIDs) {
        auto layer=findLayer(sdk,comp,id);
        for (double t : samples) {
            A_Matrix4 matrix{}; auto time=nativeTime(t);
            check(sdk.layers->AEGP_GetLayerToWorldXform(layer,&time,&matrix), "layer_to_world");
            MatrixRow row{}; row.layer=id; row.time=t;
            for (int r=0;r<4;++r) for (int c=0;c<4;++c) row.matrix[r][c]=matrix.mat[r][c];
            result.rows.push_back(row);
        }
    }
    return result;
}
}

void bindNativeAutomation(py::module_& m) {
    m.def("native_snapshot", [](int compID,int maxItems,int maxLayers) {
        ids(compID); limit(maxItems,NativeAutomation::kMaxSnapshotRows); limit(maxLayers,NativeAutomation::kMaxSnapshotRows);
        const auto data=dispatch([=] {return snapshot(compID,maxItems,maxLayers);});
        py::list items,layers;
        for (const auto& r:data.items) items.append(py::dict("id"_a=r.id,"parentId"_a=r.parent,"name"_a=r.name,"type"_a=r.type,"flags"_a=r.flags,"width"_a=r.width,"height"_a=r.height,"duration"_a=r.duration));
        for (const auto& r:data.layers) layers.append(py::dict("id"_a=r.id,"index"_a=r.index,"name"_a=r.name,"sourceId"_a=r.source,"parentId"_a=r.parent,"flags"_a=r.flags,"effects"_a=r.effects,"inPoint"_a=r.in,"outPoint"_a=r.in+r.duration,"startTime"_a=r.offset));
        auto result=base(); result["project"]=py::dict("file"_a=data.path,"dirty"_a=data.dirty,"items"_a=items,"truncated"_a=data.itemsTruncated);
        result["composition"]=py::none();
        if(data.comp) result["composition"]=py::dict("id"_a=data.comp,"frameRate"_a=data.fps,"time"_a=data.time,"numLayers"_a=data.layerCount,"layers"_a=layers,"truncated"_a=data.layersTruncated);
        return result;
    },py::arg("comp_id")=0,py::arg("max_items")=500,py::arg("max_layers")=500);

    m.def("native_sample_property", [](int compID,int layerID,py::list path,std::vector<double> samples,bool preExpression) {
        ids(compID,layerID); times(samples,NativeAutomation::kMaxSamples); auto parsed=parsePath(path);
        const auto data=dispatch([=] {return sample(compID,layerID,parsed,samples,preExpression);});
        auto result=base(); result["compId"]=data.comp; result["layerId"]=layerID; result["streamType"]=data.type;
        result["keyframeCount"]=data.keyCount; result["expressionEnabled"]=data.expression; result["times"]=samples;
        result["values"]=data.values; result["preExpression"]=preExpression; return result;
    },py::arg("comp_id"),py::arg("layer_id"),py::arg("path"),py::arg("times"),py::arg("pre_expression")=false);

    m.def("native_get_keyframes", [](int compID,int layerID,py::list path,int start,int maximum) {
        ids(compID,layerID); limit(maximum,NativeAutomation::kMaxKeys); if(start<0 || start>1000000) throw std::invalid_argument("invalid zero-based start");
        auto parsed=parsePath(path); const auto data=dispatch([=] {return readKeys(compID,layerID,parsed,start,maximum);});
        py::list rows;
        for(const auto& r:data.rows) rows.append(py::dict("index"_a=r.index,"time"_a=seconds(r.time),"timeRational"_a=py::dict("value"_a=r.time.value,"scale"_a=r.time.scale),"value"_a=py::cast(r.value),"inInterpolation"_a=r.in,"outInterpolation"_a=r.out,"flags"_a=r.flags,"temporalEase"_a=r.ease));
        auto result=base(); result["compId"]=data.comp; result["layerId"]=layerID; result["streamType"]=data.type;
        result["total"]=data.total; result["startIndex"]=start; result["keyframes"]=rows;
        result["truncated"]=start+static_cast<int>(data.rows.size())<data.total; return result;
    },py::arg("comp_id"),py::arg("layer_id"),py::arg("path"),py::arg("start_index")=0,py::arg("max_keys")=1000);

    m.def("native_set_keyframes", [](int compID,int layerID,py::list path,py::list input,bool dryRun,std::string undoName) {
        ids(compID,layerID); auto parsed=parsePath(path); limit(static_cast<int>(input.size()),NativeAutomation::kMaxKeys);
        if(undoName.empty() || undoName.size()>200 || undoName.find('\0')!=std::string::npos) throw std::invalid_argument("invalid undo name");
        std::vector<Frame> frames; std::vector<double> keyTimes;
        for(auto entry:input) {
            auto frame=py::cast<py::dict>(entry);
            if(frame.size()!=2 || !frame.contains("time") || !frame.contains("value")) throw std::invalid_argument("frame requires exactly time and value");
            if(py::isinstance<py::bool_>(frame["time"])) throw std::invalid_argument("boolean time");
            Frame row{}; row.time=py::cast<double>(frame["time"]); keyTimes.push_back(row.time);
            auto value=frame["value"];
            auto number=[](py::handle v) {
                if(py::isinstance<py::bool_>(v) || !(py::isinstance<py::int_>(v)||py::isinstance<py::float_>(v))) throw std::invalid_argument("value must be numeric");
                const auto n=py::cast<double>(v); if(!std::isfinite(n)) throw std::invalid_argument("nonfinite value"); return n;
            };
            if(py::isinstance<py::list>(value)||py::isinstance<py::tuple>(value)) {
                std::vector<double> values;
                for(auto v:py::reinterpret_borrow<py::sequence>(value)) values.push_back(number(v));
                if(values.size()<2 || values.size()>4) throw std::invalid_argument("vector requires 2..4 values");
                row.value=std::move(values);
            } else row.value=number(value);
            frames.push_back(std::move(row));
        }
        NativeAutomation::validateKeyTimes(keyTimes);
        const auto data=dispatch([=] {return writeKeys(compID,layerID,parsed,frames,dryRun,undoName);});
        auto result=base(); result["ok"]=data.ok; result["compId"]=data.comp; result["layerId"]=layerID;
        result["dryRun"]=dryRun; result["validated"]=frames.size(); result["written"]=data.written; result["outcome"]=data.outcome;
        result["error"]=data.error; result["retrySafe"]=data.outcome=="not_started";
        result["interpolation"]= "existing keys preserved; new keys use AE defaults"; return result;
    },py::arg("comp_id"),py::arg("layer_id"),py::arg("path"),py::arg("keyframes"),py::arg("dry_run")=true,py::arg("undo_name")="AE2Claude Native Keyframes");

    m.def("native_layer_transforms", [](int compID,std::vector<int> layers,std::vector<double> samples) {
        ids(compID); limit(static_cast<int>(layers.size()),64); times(samples,64);
        if(layers.size()*samples.size()>1024) throw std::invalid_argument("at most 1024 matrices per call");
        for(int layer:layers) ids(compID,layer);
        const auto data=dispatch([=] {return transforms(compID,layers,samples);});
        py::list rows; for(const auto& r:data.rows) rows.append(py::dict("layerId"_a=r.layer,"time"_a=r.time,"matrix"_a=r.matrix));
        auto result=base(); result["compId"]=data.comp; result["transforms"]=rows;
        result["convention"]="AE SDK A_Matrix4 mat[row][column], layer-to-world; includes parent transforms"; return result;
    },py::arg("comp_id"),py::arg("layer_ids"),py::arg("times"));
}
