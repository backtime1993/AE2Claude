#include "NativeAutomation.h"
#include "NativeAutomationValidation.h"
#include "Core.h"
#include "TaskUtils.h"
#include <pybind11/stl.h>
#include <array>
#include <variant>
#include <map>
#include <set>

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
            AEGP_StreamGroupingType grouping{};
            check(sdk.dynamic->AEGP_GetStreamGroupingType(get(), &grouping), "property_grouping");
            if (grouping != AEGP_StreamGroupingType_NAMED_GROUP &&
                grouping != AEGP_StreamGroupingType_INDEXED_GROUP)
                throw std::runtime_error("property_path:cannot_descend_into_leaf");
            A_long count = 0;
            check(sdk.dynamic->AEGP_GetNumStreamsInGroup(get(), &count), "property_child_count");
            if (std::holds_alternative<int>(step)) {
                const auto index = std::get<int>(step);
                if (index >= count) throw std::runtime_error("property_path:index_out_of_range");
                h = nullptr;
                const auto error = sdk.dynamic->AEGP_GetNewStreamRefByIndex(sdk.plugin, get(), index, &h);
                if (h) handles.push_back(h);
                check(error, "property_path");
                if (!h) throw std::runtime_error("property_path:not_found");
            } else {
                // ByMatchname is legal only for named groups. Passing an indexed
                // effect/mask group to it raises a modal host assertion, even on reads.
                // Enumerate both group kinds so missing/ambiguous names fail before
                // any invalid SDK lookup. All temporary handles stay inside dispatch.
                if (count > 10000) throw std::runtime_error("property_path:lookup_limit");
                Stream selected(sdk);
                const auto& wanted = std::get<std::string>(step);
                for (A_long index = 0; index < count; ++index) {
                    Stream candidate(sdk);
                    h = nullptr;
                    const auto error = sdk.dynamic->AEGP_GetNewStreamRefByIndex(sdk.plugin, get(), index, &h);
                    if (h) candidate.handles.push_back(h);
                    check(error, "property_child");
                    if (!h) throw std::runtime_error("property_child:null");
                    A_char match[AEGP_MAX_STREAM_MATCH_NAME_SIZE]{};
                    check(sdk.dynamic->AEGP_GetMatchName(h, match), "property_match_name");
                    if (wanted == match) {
                        if (!selected.handles.empty())
                            throw std::runtime_error("property_path:ambiguous_match_name; use_zero_based_index");
                        selected.handles.push_back(h);
                        candidate.handles.pop_back();
                    }
                }
                if (selected.handles.empty()) throw std::runtime_error("property_path:not_found");
                handles.push_back(selected.get());
                selected.handles.pop_back();
            }
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
Sample sampleResolved(Sdk& sdk, AEGP_CompH comp, int layerID, const Path& path, const std::vector<double>& samples, bool preExpression) {
    Sample result; result.comp=compId(sdk,comp);
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

Sample sample(int compID, int layerID, const Path& path, const std::vector<double>& samples, bool preExpression) {
    Sdk sdk;
    return sampleResolved(sdk, composition(sdk,compID), layerID, path, samples, preExpression);
}

struct PropertyRequest { int layer; Path path; };
struct Samples { int comp=0; std::vector<Sample> rows; };
Samples sampleMany(int compID, const std::vector<PropertyRequest>& properties, const std::vector<double>& times, bool preExpression) {
    Sdk sdk; auto comp=composition(sdk,compID); Samples data; data.comp=compId(sdk,comp);
    data.rows.reserve(properties.size());
    for (const auto& prop:properties) data.rows.push_back(sampleResolved(sdk,comp,prop.layer,prop.path,times,preExpression));
    return data;
}

struct FootageRow {
    int id=0, flags=0, signature=0, files=0, filesPerFrame=0;
    bool proxy=false; std::string name,path;
};
struct Footages { int scanned=0, nextOffset=0; bool truncated=false; std::vector<FootageRow> rows; };
Footages footageInventory(int offset,int maximum,bool includeProxy) {
    Sdk sdk; Footages data; auto proj=project(sdk); auto suite=sdk.suites.FootageSuite5();
    AEGP_ItemH item=nullptr;
    check(sdk.items->AEGP_GetFirstProjItem(proj,&item),"first_item");
    int index=0;
    while(item && data.scanned<maximum) {
        if(index>=offset) {
            ++data.scanned;
            AEGP_ItemType type{}; AEGP_ItemFlags flags{};
            check(sdk.items->AEGP_GetItemType(item,&type),"item_type");
            check(sdk.items->AEGP_GetItemFlags(item,&flags),"item_flags");
            for(int role=0;role<2;++role) {
                if(role==0 && type!=AEGP_ItemType_FOOTAGE) continue;
                if(role==1 && (!includeProxy || !(flags & AEGP_ItemFlag_HAS_PROXY))) continue;
                FootageRow row; row.id=itemId(sdk,item); row.flags=flags; row.proxy=role==1;
                Memory name(sdk),path(sdk); AEGP_FootageH footage=nullptr;
                check(sdk.items->AEGP_GetItemName(sdk.plugin,item,&name.handle),"item_name");row.name=name.text();
                check(role ? suite->AEGP_GetProxyFootageFromItem(item,&footage) : suite->AEGP_GetMainFootageFromItem(item,&footage),"item_footage");
                AEGP_FootageSignature signature{};
                check(suite->AEGP_GetFootageSignature(footage,&signature),"footage_signature");row.signature=signature;
                if(signature!=AEGP_FootageSignature_SOLID) {
                    A_long files=0,perFrame=0;
                    check(suite->AEGP_GetFootageNumFiles(footage,&files,&perFrame),"footage_files");
                    row.files=files;row.filesPerFrame=perFrame;
                    check(suite->AEGP_GetFootagePath(footage,0,AEGP_FOOTAGE_MAIN_FILE_INDEX,&path.handle),"footage_path");row.path=path.text();
                }
                data.rows.push_back(std::move(row));
            }
        }
        AEGP_ItemH next=nullptr;
        check(sdk.items->AEGP_GetNextProjItem(proj,item,&next),"next_item");item=next;++index;
    }
    data.truncated=item!=nullptr;data.nextOffset=index;return data;
}

struct Key { A_Time time{}; Value value; int index=0, in=0, out=0, flags=0; std::vector<std::array<double,4>> ease; std::vector<Value> tangents; };
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
        if(type==AEGP_StreamType_TwoD_SPATIAL || type==AEGP_StreamType_ThreeD_SPATIAL) {
            OwnedValue incoming(sdk),outgoing(sdk);
            check(sdk.keys->AEGP_GetNewKeyframeSpatialTangents(sdk.plugin,stream.get(),i,&incoming.value,&outgoing.value),"spatial_tangents");
            incoming.owned=true;outgoing.owned=true;
            row.tangents={unpack(type,incoming.value),unpack(type,outgoing.value)};
        }
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

// Preflight is completed by the caller before opening this single undo group.
// A partial SDK failure has unknown outcome: never automatically replay writes.
template<typename F> WriteResult undoWrite(Sdk& sdk,WriteResult result,bool dryRun,const std::string& name,F operation) {
    if(dryRun) return result;
    check(sdk.suites.UtilitySuite6()->AEGP_StartUndoGroup(name.c_str()),"start_undo");
    try { operation(result);result.outcome="completed"; }
    catch(const std::exception& e) {result.ok=false;result.error=e.what();result.outcome="unknown";}
    if(sdk.suites.UtilitySuite6()->AEGP_EndUndoGroup()!=A_Err_NONE) {
        result.ok=false;result.error+=";end_undo_failed";result.outcome="unknown";
    }
    return result;
}

struct EaseFrame { int index;std::vector<std::array<double,4>> ease; };
WriteResult writeEase(int compID,int layerID,const Path& path,const std::vector<EaseFrame>& frames,bool dryRun,const std::string& name) {
    Sdk sdk;WriteResult result;auto comp=composition(sdk,compID);result.comp=compId(sdk,comp);
    auto layer=findLayer(sdk,comp,layerID);AEGP_LayerFlags flags{};
    check(sdk.layers->AEGP_GetLayerFlags(layer,&flags),"layer_flags");
    if(flags & AEGP_LayerFlag_LOCKED) throw std::runtime_error("layer_is_locked; outcome=not_started");
    Stream stream(sdk);stream.resolve(layer,path);AEGP_StreamType type{};A_long count=0;A_short dims=0;
    check(sdk.streams->AEGP_GetStreamType(stream.get(),&type),"stream_type");dimensions(type);
    AEGP_KeyInterpolationMask interpolation{};
    check(sdk.streams->AEGP_GetValidInterpolations(stream.get(), &interpolation), "valid_interpolations");
    if (!(interpolation & AEGP_KeyInterpMask_BEZIER))
        throw std::runtime_error("bezier_interpolation_not_supported; outcome=not_started");
    check(sdk.keys->AEGP_GetStreamNumKFs(stream.get(),&count),"keyframe_count");
    check(sdk.keys->AEGP_GetStreamTemporalDimensionality(stream.get(),&dims),"temporal_dimensions");
    for(const auto& row:frames) {
        if(row.index>=count) throw std::runtime_error("key_index_out_of_range; outcome=not_started");
        if(row.ease.size()!=static_cast<std::size_t>(dims)) throw std::runtime_error("temporal_dimension_mismatch; outcome=not_started");
        AEGP_KeyframeFlags keyFlags{};
        check(sdk.keys->AEGP_GetKeyframeFlags(stream.get(),row.index,&keyFlags),"keyframe_flags");
        if(keyFlags & AEGP_KeyframeFlag_ROVING) throw std::runtime_error("roving_key_not_supported; outcome=not_started");
    }
    return undoWrite(sdk,result,dryRun,name,[&](WriteResult& r){
        for(const auto& row:frames) {
            check(sdk.keys->AEGP_SetKeyframeFlag(stream.get(),row.index,AEGP_KeyframeFlag_TEMPORAL_AUTOBEZIER,FALSE),"clear_auto_ease");
            check(sdk.keys->AEGP_SetKeyframeFlag(stream.get(),row.index,AEGP_KeyframeFlag_TEMPORAL_CONTINUOUS,FALSE),"clear_continuous_ease");
            check(sdk.keys->AEGP_SetKeyframeInterpolation(stream.get(),row.index,AEGP_KeyInterp_BEZIER,AEGP_KeyInterp_BEZIER),"set_bezier");
            for(A_short d=0;d<dims;++d) {
                const auto& e=row.ease[d];AEGP_KeyframeEase in{e[0],e[1]},out{e[2],e[3]};
                check(sdk.keys->AEGP_SetKeyframeTemporalEase(stream.get(),row.index,d,&in,&out),"set_temporal_ease");
            }
            ++r.written;
        }
    });
}

const std::map<std::string,AEGP_LayerFlags> controlFlags={
    {"enabled",AEGP_LayerFlag_VIDEO_ACTIVE},{"audio_active",AEGP_LayerFlag_AUDIO_ACTIVE},
    {"effects_active",AEGP_LayerFlag_EFFECTS_ACTIVE},{"motion_blur",AEGP_LayerFlag_MOTION_BLUR},
    {"shy",AEGP_LayerFlag_SHY},{"solo",AEGP_LayerFlag_SOLO},
    {"guide",AEGP_LayerFlag_GUIDE_LAYER},{"adjustment",AEGP_LayerFlag_ADJUSTMENT_LAYER}};
const std::map<std::string,PF_TransferMode> blendModes={
    {"normal",PF_Xfer_IN_FRONT},{"add",PF_Xfer_ADD},{"multiply",PF_Xfer_MULTIPLY},
    {"screen",PF_Xfer_SCREEN},{"overlay",PF_Xfer_OVERLAY},{"difference",PF_Xfer_DIFFERENCE2}};
struct LayerChange { int id;std::map<std::string,bool> flags;std::string blend; };
NativeAutomation::LayerControlType layerControlType(AEGP_ObjectType type) {
    using NativeAutomation::LayerControlType;
    switch(type) {
        case AEGP_ObjectType_AV: return LayerControlType::AV;
        case AEGP_ObjectType_TEXT: return LayerControlType::Text;
        case AEGP_ObjectType_VECTOR: return LayerControlType::Shape;
        default: return LayerControlType::Other;
    }
}
WriteResult writeLayers(int compID,const std::vector<LayerChange>& changes,bool dryRun,const std::string& name) {
    Sdk sdk;WriteResult result;auto comp=composition(sdk,compID);result.comp=compId(sdk,comp);
    std::vector<AEGP_LayerH> layers;std::vector<AEGP_LayerTransferMode> modes;
    for(const auto& row:changes) {
        auto layer=findLayer(sdk,comp,row.id);AEGP_LayerFlags flags{};AEGP_ObjectType type{};AEGP_LayerTransferMode mode{};
        check(sdk.layers->AEGP_GetLayerFlags(layer,&flags),"layer_flags");
        if(flags & AEGP_LayerFlag_LOCKED) throw std::runtime_error("layer_is_locked; outcome=not_started");
        check(sdk.layers->AEGP_GetLayerObjectType(layer,&type),"layer_type");
        NativeAutomation::validateLayerControls(layerControlType(type),row.flags,!row.blend.empty());
        if(!row.blend.empty()) {
            const auto error=sdk.layers->AEGP_GetLayerTransferMode(layer,&mode);
            if(error!=A_Err_NONE)
                throw std::runtime_error("layer_blend:sdk_error="+std::to_string(error)+"; outcome=not_started");
            mode.mode=blendModes.at(row.blend); // Preserve transfer flags and track matte.
        }
        layers.push_back(layer);modes.push_back(mode);
    }
    return undoWrite(sdk,result,dryRun,name,[&](WriteResult& r){
        for(std::size_t i=0;i<changes.size();++i) {
            for(const auto& flag:changes[i].flags) check(sdk.layers->AEGP_SetLayerFlag(layers[i],controlFlags.at(flag.first),flag.second),"set_layer_flag");
            if(!changes[i].blend.empty()) check(sdk.layers->AEGP_SetLayerTransferMode(layers[i],&modes[i]),"set_layer_blend");
            ++r.written;
        }
    });
}

py::dict writeResponse(const WriteResult& data,bool dryRun,std::size_t validated) {
    auto result=base();result["ok"]=data.ok;result["compId"]=data.comp;result["dryRun"]=dryRun;
    result["validated"]=validated;result["written"]=data.written;result["outcome"]=data.outcome;
    result["error"]=data.error;result["retrySafe"]=data.outcome=="not_started";return result;
}
void validUndo(const std::string& name) {
    if(name.empty() || name.size()>200 || name.find('\0')!=std::string::npos) throw std::invalid_argument("invalid undo name");
}
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
    A_char match[AEGP_MAX_STREAM_MATCH_NAME_SIZE]{};
    check(sdk.dynamic->AEGP_GetMatchName(stream.get(), match), "property_match_name");
    const bool twoDimensionalPosition = !(flags & AEGP_LayerFlag_LAYER_IS_3D)
        && type == AEGP_StreamType_ThreeD_SPATIAL && std::string(match) == "ADBE Position";
    try {
    for (const auto& frame : frames) {
        Value value = frame.value;
        if (twoDimensionalPosition && std::holds_alternative<std::vector<double>>(value)) {
            auto& vector = std::get<std::vector<double>>(value);
            if (vector.size() == 2) vector.push_back(0.0);
        }
        values.push_back(pack(stream.get(),type,value));
        timeValues.push_back(nativeTime(frame.time));
    }
    } catch (const std::exception& error) {
        result.ok = false; result.error = error.what();
        return result; // No undo group or keyframe mutation has begun.
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
    m.def("native_set_keyframe_ease",[](int compID,int layerID,py::list path,py::list input,bool dryRun,std::string name){
        ids(compID,layerID);validUndo(name);auto parsed=parsePath(path);limit(static_cast<int>(input.size()),NativeAutomation::kMaxKeys);
        std::vector<EaseFrame> frames;std::set<int> seen;
        for(auto entry:input) {
            auto row=py::cast<py::dict>(entry);
            if(row.size()!=2 || !row.contains("index") || !row.contains("temporal_ease")) throw std::invalid_argument("ease key requires index and temporal_ease");
            if(py::isinstance<py::bool_>(row["index"])) throw std::invalid_argument("boolean key index");
            int index=py::cast<int>(row["index"]);
            if(index<0 || index>1000000 || !seen.insert(index).second) throw std::invalid_argument("invalid/duplicate key index");
            auto ease=py::cast<py::list>(row["temporal_ease"]);limit(static_cast<int>(ease.size()),4);EaseFrame frame{index,{}};
            for(auto dimension:ease) {
                auto values=py::cast<py::list>(dimension);
                if(values.size()!=4) throw std::invalid_argument("ease dimension requires four numbers");
                std::array<double,4> e{};
                for(int i=0;i<4;++i) {
                    auto v=values[i];
                    if(py::isinstance<py::bool_>(v) || !(py::isinstance<py::float_>(v)||py::isinstance<py::int_>(v))) throw std::invalid_argument("ease must be numeric");
                    e[i]=py::cast<double>(v);
                    if(!std::isfinite(e[i])) throw std::invalid_argument("nonfinite ease");
                }
                if(e[1]<0.001 || e[1]>1 || e[3]<0.001 || e[3]>1) throw std::invalid_argument("influence must be 0.001..1");
                frame.ease.push_back(e);
            }
            frames.push_back(std::move(frame));
        }
        const auto data=dispatch([=]{return writeEase(compID,layerID,parsed,frames,dryRun,name);});
        auto result=writeResponse(data,dryRun,frames.size());result["layerId"]=layerID;return result;
    },py::arg("comp_id"),py::arg("layer_id"),py::arg("path"),py::arg("keyframes"),py::arg("dry_run")=true,py::arg("undo_name")="AE2Claude Native Keyframe Ease");

    m.def("native_set_layer_controls",[](int compID,py::list input,bool dryRun,std::string name){
        ids(compID);validUndo(name);limit(static_cast<int>(input.size()),256);std::set<int> seen;std::vector<LayerChange> changes;
        for(auto entry:input) {
            auto row=py::cast<py::dict>(entry);
            for(auto item:row) {auto key=py::cast<std::string>(item.first);if(key!="layer_id" && key!="flags" && key!="blend_mode") throw std::invalid_argument("unknown layer field");}
            if(!row.contains("layer_id") || py::isinstance<py::bool_>(row["layer_id"])) throw std::invalid_argument("invalid layer_id");
            LayerChange change{};change.id=py::cast<int>(row["layer_id"]);ids(compID,change.id);
            if(!seen.insert(change.id).second) throw std::invalid_argument("duplicate layer_id");
            if(row.contains("flags")) for(auto flag:py::cast<py::dict>(row["flags"])) {
                auto key=py::cast<std::string>(flag.first);
                if(!controlFlags.count(key) || !py::isinstance<py::bool_>(flag.second)) throw std::invalid_argument("invalid layer flag");
                change.flags.emplace(key,py::cast<bool>(flag.second));
            }
            if(row.contains("blend_mode")) {change.blend=py::cast<std::string>(row["blend_mode"]);if(!blendModes.count(change.blend)) throw std::invalid_argument("invalid blend_mode");}
            if(change.flags.empty() && change.blend.empty()) throw std::invalid_argument("empty layer change");
            changes.push_back(std::move(change));
        }
        const auto data=dispatch([=]{return writeLayers(compID,changes,dryRun,name);});return writeResponse(data,dryRun,changes.size());
    },py::arg("comp_id"),py::arg("changes"),py::arg("dry_run")=true,py::arg("undo_name")="AE2Claude Native Layer Controls");

    m.def("native_sample_properties", [](int compID,py::list input,std::vector<double> samples,bool preExpression) {
        ids(compID);limit(static_cast<int>(input.size()),64);times(samples,NativeAutomation::kMaxSamples);
        if(input.size()*samples.size()>4096) throw std::invalid_argument("at most 4096 property/time samples");
        std::vector<PropertyRequest> properties;properties.reserve(input.size());
        for(auto entry:input) {
            auto prop=py::cast<py::dict>(entry);
            if(prop.size()!=2 || !prop.contains("layer_id") || !prop.contains("path")) throw std::invalid_argument("property requires layer_id and path");
            if(py::isinstance<py::bool_>(prop["layer_id"])) throw std::invalid_argument("boolean layer_id");
            int layer=py::cast<int>(prop["layer_id"]);ids(compID,layer);
            properties.push_back({layer,parsePath(py::cast<py::list>(prop["path"]))});
        }
        const auto data=dispatch([=]{return sampleMany(compID,properties,samples,preExpression);});
        py::list rows;
        for(std::size_t i=0;i<data.rows.size();++i) {
            const auto& r=data.rows[i];
            rows.append(py::dict("layerId"_a=properties[i].layer,"streamType"_a=r.type,"keyframeCount"_a=r.keyCount,"expressionEnabled"_a=r.expression,"values"_a=r.values));
        }
        auto result=base();result["compId"]=data.comp;result["times"]=samples;result["properties"]=rows;result["preExpression"]=preExpression;return result;
    },py::arg("comp_id"),py::arg("properties"),py::arg("times"),py::arg("pre_expression")=false);

    m.def("native_footage_inventory", [](int offset,int maximum,bool includeProxy) {
        if(offset<0 || offset>100000) throw std::invalid_argument("offset outside 0..100000");
        limit(maximum,NativeAutomation::kMaxSnapshotRows);
        const auto data=dispatch([=]{return footageInventory(offset,maximum,includeProxy);});
        py::list rows;
        for(const auto& r:data.rows) rows.append(py::dict("itemId"_a=r.id,"name"_a=r.name,"proxy"_a=r.proxy,"path"_a=r.path,"signature"_a=r.signature,"numMainFiles"_a=r.files,"filesPerFrame"_a=r.filesPerFrame,"missing"_a=bool(r.flags & (r.proxy?AEGP_ItemFlag_MISSING_PROXY:AEGP_ItemFlag_MISSING)),"usingProxy"_a=bool(r.flags & AEGP_ItemFlag_USING_PROXY)));
        auto result=base();result["footage"]=rows;result["offset"]=offset;result["scannedItems"]=data.scanned;result["truncated"]=data.truncated;
        if(data.truncated) result["nextOffset"]=data.nextOffset;else result["nextOffset"]=py::none();
        result["pathScope"]="first main file per footage source; missing flags reflect AE state, not a filesystem scan";return result;
    },py::arg("offset")=0,py::arg("max_items")=500,py::arg("include_proxy")=true);

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
        for(const auto& r:data.rows) rows.append(py::dict("index"_a=r.index,"time"_a=seconds(r.time),"timeRational"_a=py::dict("value"_a=r.time.value,"scale"_a=r.time.scale),"value"_a=py::cast(r.value),"inInterpolation"_a=r.in,"outInterpolation"_a=r.out,"flags"_a=r.flags,"temporalEase"_a=r.ease,"spatialTangents"_a=r.tangents));
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
