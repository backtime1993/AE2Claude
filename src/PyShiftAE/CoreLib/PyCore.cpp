#include "PyCore.h"
#include "../CoreSDK/StreamSuites.h"
#include "../CoreSDK/KeyframeSuites.h"
#include "../CoreSDK/EffectSuites.h"
#include "../CoreSDK/FootageSuites.h"
#include "../CoreSDK/ItemSuites.h"
#include "../CoreSDK/ProjectSuites.h"
#include "../CoreSDK/TaskUtilsQuiet.h"
#include <filesystem>

// Macro: first call in a chain uses enqueueSyncTask (wakes idle), rest use quiet version
#define ENQUEUE_FIRST enqueueSyncTask
#define ENQUEUE_CHAIN enqueueSyncTaskQuiet

/*
* PyCore.cpp
* This file contains the definitions for the functions that bind the C++ classes to Python.
* The functions are called from PyLink.cpp.
* e.x. bindItem(m) is called from PyLink.cpp to bind the Item class to Python.
*
*
*/

void Manifest::validate()
{
    //validate the manifest
    this->_validate_versions();
    this->_validate_paths();
    this->_validate_dependencies();
}

void Manifest::load()
{
    //load the manifest
    this->_load_main();
}

void Manifest::_validate_versions()
{
    //validate the version of AE and python are valid
    auto& valid_versions = this->_validVersions;
    auto& AE_VERS = this->AE_VERS;

    // Validate AE versions
    for (auto& version : AE_VERS) {
        if (std::find(valid_versions.begin(), valid_versions.end(), version) == valid_versions.end()) {
            throw std::invalid_argument("Invalid AE version: " + version);
        }
    }
}

void Manifest::_validate_paths()
{
    //validate that the paths to the manifest, main script, ui script, and resources, and extras are valid. main script and UI always there. resources and extras optional
    auto& entry = this->_entry;

    if (!std::filesystem::exists(entry)) {
        throw std::invalid_argument("Missing entry script: " + entry);
    }

}

void Manifest::_validate_dependencies()
{
    //validate that the dependencies are installed
    auto& dependencies = this->_dependencies;
    for (auto& dependency : dependencies) {
        try {
            py::module_::import(dependency.c_str());
        }
        catch (py::error_already_set& e) {
            throw std::invalid_argument("Missing dependency: " + dependency);
        }
    }
}

void Manifest::_load_main()
{
    //take the main path and import it as a module
    auto& entry = this->_entry;

    // Load main script
    py::module_ main = py::module_::import(entry.c_str());
    this->_main = main;

}

void bindLayerEnum(py::module_& m)
{
    py::enum_<qualityOptions>(m, "Quality")
        .value("BEST", qualityOptions::BEST)
        .value("DRAFT", qualityOptions::DRAFT)
        .value("WIREFRAME", qualityOptions::WIREFRAME)
        .value("NONE", qualityOptions::NONE)
        .export_values();

    py::enum_<LayerFlag>(m, "LayerFlag")
        .value("VIDEO_ACTIVE", LayerFlag::VIDEO_ACTIVE)
        .value("AUDIO_ACTIVE", LayerFlag::AUDIO_ACTIVE)
        .value("EFFECTS_ACTIVE", LayerFlag::EFFECTS_ACTIVE)
        .value("MOTION_BLUR", LayerFlag::MOTION_BLUR)
        .value("FRAME_BLENDING", LayerFlag::FRAME_BLENDING)
        .value("LOCKED", LayerFlag::LOCKED)
        .value("SHY", LayerFlag::SHY)
        .value("COLLAPSE", LayerFlag::COLLAPSE)
        .value("AUTO_ORIENT_ROTATION", LayerFlag::AUTO_ORIENT_ROTATION)
        .value("ADJUSTMENT_LAYER", LayerFlag::ADJUSTMENT_LAYER)
        .value("TIME_REMAPPING", LayerFlag::TIME_REMAPPING)
        .value("LAYER_IS_3D", LayerFlag::LAYER_IS_3D)
        .value("LOOK_AT_CAMERA", LayerFlag::LOOK_AT_CAMERA)
        .value("LOOK_AT_POI", LayerFlag::LOOK_AT_POI)
        .value("SOLO", LayerFlag::SOLO)
        .value("MARKERS_LOCKED", LayerFlag::MARKERS_LOCKED)
        .value("NULL_LAYER", LayerFlag::NULL_LAYER)
        .value("HIDE_LOCKED_MASKS", LayerFlag::HIDE_LOCKED_MASKS)
        .value("GUIDE_LAYER", LayerFlag::GUIDE_LAYER)
        .value("ADVANCED_FRAME_BLENDING", LayerFlag::ADVANCED_FRAME_BLENDING)
        .value("SUBLAYERS_RENDER_SEPARATELY", LayerFlag::SUBLAYERS_RENDER_SEPARATELY)
        .value("ENVIRONMENT_LAYER", LayerFlag::ENVIRONMENT_LAYER)
        .export_values();

	
}


void bindLayer(py::module_& m)
{
    py::class_<Layer, std::shared_ptr<Layer>>(m, "Layer")
        .def(py::init<const Result<AEGP_LayerH>&>())
        .def_property("name", &Layer::GetLayerName, &Layer::SetLayerName)
        .def_property("quality", &Layer::getQuality, &Layer::setQuality)
        .def_property("startTime", &Layer::getOffset, &Layer::setOffset) //CHANGE IN DOCS
        .def_property("index", &Layer::index, &Layer::changeIndex)
        .def_property("video_active", [](Layer& self) {return self.getFlag(LayerFlag::VIDEO_ACTIVE); },
            			[](Layer& self, bool value) {self.setFlag(LayerFlag::VIDEO_ACTIVE, value); })
        .def_property("audio_active", [](Layer& self) {return self.getFlag(LayerFlag::AUDIO_ACTIVE); },
            						[](Layer& self, bool value) {self.setFlag(LayerFlag::AUDIO_ACTIVE, value); })
        .def_property("effects_active", [](Layer& self) {return self.getFlag(LayerFlag::EFFECTS_ACTIVE); },
            									[](Layer& self, bool value) {self.setFlag(LayerFlag::EFFECTS_ACTIVE, value); })
        .def_property("motion_blur", [](Layer& self) {return self.getFlag(LayerFlag::MOTION_BLUR); },
            [](Layer& self, bool value) {self.setFlag(LayerFlag::MOTION_BLUR, value); })
        .def_property("frame_blending", [](Layer& self) {return self.getFlag(LayerFlag::FRAME_BLENDING); },
            			[](Layer& self, bool value) {self.setFlag(LayerFlag::FRAME_BLENDING, value); })
        .def_property("locked", [](Layer& self) {return self.getFlag(LayerFlag::LOCKED); },
            								[](Layer& self, bool value) {self.setFlag(LayerFlag::LOCKED, value); })
        .def_property("shy", [](Layer& self) {return self.getFlag(LayerFlag::SHY); },
            [](Layer& self, bool value) {self.setFlag(LayerFlag::SHY, value); })
        .def_property("collapse", [](Layer& self) {return self.getFlag(LayerFlag::COLLAPSE); },
            										[](Layer& self, bool value) {self.setFlag(LayerFlag::COLLAPSE, value); })
        .def_property("auto_orient_rotation", [](Layer& self) {return self.getFlag(LayerFlag::AUTO_ORIENT_ROTATION); },
            															[](Layer& self, bool value) {self.setFlag(LayerFlag::AUTO_ORIENT_ROTATION, value); })
        .def_property("adjustment_layer", [](Layer& self) {return self.getFlag(LayerFlag::ADJUSTMENT_LAYER); },
            			[](Layer& self, bool value) {self.setFlag(LayerFlag::ADJUSTMENT_LAYER, value); })
        .def_property("time_remapping", [](Layer& self) {return self.getFlag(LayerFlag::TIME_REMAPPING); },
            												[](Layer& self, bool value) {self.setFlag(LayerFlag::TIME_REMAPPING, value); })
        .def_property("layer_is_3d", [](Layer& self) {return self.getFlag(LayerFlag::LAYER_IS_3D); },
            [](Layer& self, bool value) {self.setFlag(LayerFlag::LAYER_IS_3D, value); })
        .def_property("look_at_camera", [](Layer& self) {return self.getFlag(LayerFlag::LOOK_AT_CAMERA); },
            															[](Layer& self, bool value) {self.setFlag(LayerFlag::LOOK_AT_CAMERA, value); })
        .def_property("look_at_poi", [](Layer& self) {return self.getFlag(LayerFlag::LOOK_AT_POI); },
            			[](Layer& self, bool value) {self.setFlag(LayerFlag::LOOK_AT_POI, value); })
        .def_property("solo", [](Layer& self) {return self.getFlag(LayerFlag::SOLO); },
            											[](Layer& self, bool value) {self.setFlag(LayerFlag::SOLO, value); })
        .def_property("markers_locked", [](Layer& self) {return self.getFlag(LayerFlag::MARKERS_LOCKED); },
            																[](Layer& self, bool value) {self.setFlag(LayerFlag::MARKERS_LOCKED, value); })
        .def_property("null_layer", [](Layer& self) {return self.getFlag(LayerFlag::NULL_LAYER); },
            				[](Layer& self, bool value) {self.setFlag(LayerFlag::NULL_LAYER, value); })
        .def_property("hide_locked_masks", [](Layer& self) {return self.getFlag(LayerFlag::HIDE_LOCKED_MASKS); },
            																			[](Layer& self, bool value) {self.setFlag(LayerFlag::HIDE_LOCKED_MASKS, value); })
        .def_property("guide_layer", [](Layer& self) {return self.getFlag(LayerFlag::GUIDE_LAYER); },
            				[](Layer& self, bool value) {self.setFlag(LayerFlag::GUIDE_LAYER, value); })
        .def_property("advanced_frame_blending", [](Layer& self) {return self.getFlag(LayerFlag::ADVANCED_FRAME_BLENDING); },
            																							[](Layer& self, bool value) {self.setFlag(LayerFlag::ADVANCED_FRAME_BLENDING, value); })
        .def_property("sublayers_render_separately", [](Layer& self) {return self.getFlag(LayerFlag::SUBLAYERS_RENDER_SEPARATELY); },
            																												[](Layer& self, bool value) {self.setFlag(LayerFlag::SUBLAYERS_RENDER_SEPARATELY, value); })
        .def_property("environment_layer", [](Layer& self) {return self.getFlag(LayerFlag::ENVIRONMENT_LAYER); },
            				[](Layer& self, bool value) {self.setFlag(LayerFlag::ENVIRONMENT_LAYER, value); })

        .def_property_readonly("sourceName", &Layer::GetSourceName)
        .def_property_readonly("time", &Layer::layerTime) 
        .def_property_readonly("compTime", &Layer::layerCompTime) 
        .def_property_readonly("inPoint", &Layer::inPoint) 
        .def_property_readonly("compInPoint", &Layer::compInPoint) 
        .def_property_readonly("duration", &Layer::duration)
        .def_property_readonly("compDuration", &Layer::compDuration) 
        .def_property_readonly("source", &Layer::getSource, py::return_value_policy::reference)
        .def("addEffect", &Layer::addEffect, py::arg("effect"), py::return_value_policy::reference)
        .def("delete", [](Layer& self) {
            py::gil_scoped_release release;
            self.deleteLayer();
        })
        .def("duplicate", [](Layer& self) -> std::shared_ptr<Layer> {
            py::gil_scoped_release release;
            return self.duplicate();
        })
        .def_property("parent",
            [](Layer& self) -> std::shared_ptr<Layer> {
                py::gil_scoped_release release;
                return self.getParentLayer();
            },
            [](Layer& self, std::shared_ptr<Layer> p) {
                py::gil_scoped_release release;
                self.setParentLayer(p);
            },
            py::return_value_policy::reference)
        .def("removeParent", [](Layer& self) {
            py::gil_scoped_release release;
            self.removeParent();
        })
        .def_property("label", &Layer::getLabel, &Layer::setLabel)
        .def_property_readonly("layerID", &Layer::getLayerID)
        .def_property_readonly("is3D", &Layer::isLayer3D)
        .def_property("transferMode", &Layer::getTransferMode, &Layer::setTransferMode)
        .def_property_readonly("stretch", &Layer::getStretch)
        .def_property_readonly("objectType", &Layer::getObjectType)
        .def_property("samplingQuality", &Layer::getSamplingQuality, &Layer::setSamplingQuality)
        .def("convertCompToLayerTime", &Layer::convertCompToLayerTime, py::arg("comp_time"))
        .def("convertLayerToCompTime", &Layer::convertLayerToCompTime, py::arg("layer_time"))
        .def("renderFramePixels", &Layer::renderFramePixels,
            py::arg("time") = -1.0f,
            py::arg("maxDimension") = 0,
            "Render a layer frame and return RGBA pixel data as numpy array (H, W, 4). "
            "When maxDimension > 0, applies layer render downsample.");

}

void bindLayerCollection(py::module_& m) {
    auto normalize_index = [](py::ssize_t i, std::size_t size) -> std::size_t {
        if (i < 0) {
            i += static_cast<py::ssize_t>(size);
        }
        if (i < 0 || static_cast<std::size_t>(i) >= size) {
            throw py::index_error();
        }
        return static_cast<std::size_t>(i);
    };

    py::class_<LayerCollection, std::shared_ptr<LayerCollection>>(m, "LayerCollection")
        .def(py::init<const Result<AEGP_CompH>&, std::vector<std::shared_ptr<Layer>>>()) // Updated constructor
        .def("__getitem__", [normalize_index](const LayerCollection& c, py::ssize_t i) {
        return c[normalize_index(i, c.size())];
            }, py::return_value_policy::reference) // Return Layer as reference
        .def("__setitem__", [normalize_index](LayerCollection& c, py::ssize_t i, std::shared_ptr<Layer> l) {
                c[normalize_index(i, c.size())] = l;
            })
        .def("__len__", [](const LayerCollection& c) { return c.size(); })
        .def("__iter__", [](const LayerCollection& c) {
        return py::make_iterator(c.begin(), c.end());
            }, py::keep_alive<0, 1>()) // Use const-qualified begin and end



           //define __str__ method, which gets the comp name for the collection
        .def("__str__", [](LayerCollection& c) {
            return c.getCompName();
            })

        .def("append", &LayerCollection::addLayerToCollection, py::arg("layer"), py::arg("index") = -1)
        .def("insert", &LayerCollection::addLayerToCollection, py::arg("layer"), py::arg("index"))
        .def("remove", &LayerCollection::removeLayerFromCollection, py::arg("layer"))
        .def("pop", &LayerCollection::RemoveLayerByIndex, py::arg("index") = -1)
        .def("getAllLayers", &LayerCollection::getAllLayers);

}

void bindSolidItem(py::module_& m)
{
    py::class_<SolidItem, FootageItem, std::shared_ptr<SolidItem>>(m, "SolidItem")
        .def(py::init(&SolidItem::createNew), py::arg("name") = "New Solid", py::arg("width") = 0,
            py::arg("height") = 0, py::arg("red") = 0, py::arg("green") = 0, py::arg("blue") = 0, py::arg("alpha") = 0, py::arg("duration") = 0, py::arg("index") = -1);
}

void bindItem(py::module_& m)
{
    py::class_<Item, std::shared_ptr<Item>>(m, "Item")
        .def(py::init<const Result<AEGP_ItemH>&>())
        .def_property_readonly("width", &Item::getWidth)
        .def_property_readonly("height", &Item::getHeight)
        .def_property_readonly("duration", &Item::getDuration)
        .def_property("time", &Item::getCurrentTime, &Item::setCurrentTime)
        .def_property("selected", &Item::isSelected, &Item::setSelected)
        .def_property("name",
            &Item::getName,
            &Item::setName)
        .def("renderFramePixels", &Item::renderFramePixels,
            py::arg("time") = -1.0f,
            py::arg("maxDimension") = 0,
            "Render an item frame and return RGBA pixel data as numpy array (H, W, 4). "
            "When maxDimension > 0, applies render downsample so the output fits roughly within that size.");
}

void bindItemCollection(py::module_& m) {
    py::class_<ItemCollection, std::shared_ptr<ItemCollection>>(m, "ItemCollection")
        .def(py::init<const Result<AEGP_ItemH>&>())
        .def("__getitem__", [](const ItemCollection& c, int i) {
            // Handle negative index
            size_t index = (i < 0) ? c.size() + i : i;

            if (index >= c.size()) throw py::index_error();
            return c[index];
                }, py::return_value_policy::reference) // Return Item as reference


        .def("__len__", [](const ItemCollection& c) { return c.size(); })
        .def("__iter__", [](const ItemCollection& c) {
        return py::make_iterator(c.begin(), c.end());
            }, py::keep_alive<0, 1>()) // Use const-qualified begin and end

        .def("append", &ItemCollection::append, py::arg("item"))
        .def("remove", &ItemCollection::remove, py::arg("item"));
}

void bindCompItem(py::module_& m)
{
    /*
    static CompItem CreateNew(std::string name, float width, float height, float frameRate, float duration, float aspectRatio) { */
    py::class_<CompItem, Item, std::shared_ptr<CompItem>>(m, "CompItem")
        .def(py::init(&CompItem::CreateNew),
            py::arg("name") = "New Comp",
            py::arg("width") = 1920,
            py::arg("height") = 1080,
            py::arg("frameRate") = 24.0,
            py::arg("duration") = 10,
            py::arg("aspectRatio") = 1.0)
        .def_property_readonly("layer", &CompItem::getLayers, py::return_value_policy::reference)
        .def_property_readonly("layers", &CompItem::getLayers, py::return_value_policy::reference)
        .def_property_readonly("selectedLayers", &CompItem::getSelectedLayers, py::return_value_policy::reference)
        .def_property_readonly("selectedLayer", &CompItem::getSelectedLayers, py::return_value_policy::reference)
        .def_property_readonly("numLayers", &CompItem::NumLayers)
        .def_property("width", &Item::getWidth, &CompItem::setWidth)
        .def_property("height", &Item::getHeight, &CompItem::setHeight)
        .def_property("duration", &CompItem::getDuration, &CompItem::setDuration)
        .def_property("time", &CompItem::getCurrentTime, &CompItem::setCurrentTime)
        .def_property("frameRate",//ADD TO DOCS
            &CompItem::getFrameRate,
            &CompItem::setFrameRate)
        .def("addSolid", &CompItem::addSolid,
            py::arg("name"), py::arg("w"), py::arg("h"),
            py::arg("r"), py::arg("g"), py::arg("b"), py::arg("a"), py::arg("dur"),
            py::return_value_policy::reference)
        .def("addNull", &CompItem::addNull,
            py::arg("name") = "Null", py::arg("dur") = 0,
            py::return_value_policy::reference)
        .def("addCamera", &CompItem::addCamera,
            py::arg("name"), py::arg("x"), py::arg("y"),
            py::return_value_policy::reference)
        .def("addLight", &CompItem::addLight,
            py::arg("name"), py::arg("x"), py::arg("y"),
            py::return_value_policy::reference)
        .def("addText", &CompItem::addText,
            py::arg("select") = true,
            py::return_value_policy::reference)
        .def("addShape", &CompItem::addShape,
            py::return_value_policy::reference)
        .def_property("bgColor", &CompItem::getBGColor,
            [](CompItem& self, std::vector<float> c) { self.setBGColor(c[0], c[1], c[2]); })
        .def_property_readonly("workAreaStart", &CompItem::getWorkAreaStart)
        .def_property_readonly("workAreaDuration", &CompItem::getWorkAreaDuration)
        .def("setWorkArea", &CompItem::setWorkArea, py::arg("start"), py::arg("duration"))
        .def_property("displayStartTime", &CompItem::getDisplayStartTime, &CompItem::setDisplayStartTime)
        .def("duplicateComp", &CompItem::duplicateComp, py::return_value_policy::reference)
        .def("renderFramePixels", &CompItem::renderFramePixels,
            py::arg("time") = -1.0f,
            py::arg("maxDimension") = 0,
            "Render a frame and return RGBA pixel data as numpy array (H, W, 4). "
            "When maxDimension > 0, applies render downsample so the output fits roughly within that size.");
}

void bindFootageItem(py::module_& m)
{
    py::class_<FootageItem, Item, std::shared_ptr<FootageItem>>(m, "FootageItem")
        .def(py::init(&FootageItem::createNew), py::arg("name") = "New Layer", py::arg("path") = NULL, py::arg("index") = -1)
        .def_property_readonly("path", &FootageItem::getPath)
        .def("replace", &FootageItem::replaceWithNewSource, py::arg("name"), py::arg("path"));
}

void bindProjectCollection(py::module_& m) {
    py::class_<ProjectCollection, std::shared_ptr<ProjectCollection>>(m, "ProjectCollection")
        .def(py::init<const Result<AEGP_ProjectH>&>())
        .def("__getitem__", [](const ProjectCollection& c, int i) {
            // Handle negative index by converting it to positive
            size_t index = (i < 0) ? c.size() + i : i;

            if (index >= c.size()) throw py::index_error();
            return c[index];
                }, py::return_value_policy::reference) // Return Item as reference

        .def("__len__", [](const ProjectCollection& c) { return c.size(); })
        .def("__iter__", [](const ProjectCollection& c) {
            return py::make_iterator(c.begin(), c.end());
            }, py::keep_alive<0, 1>()) // Use const-qualified begin and end

        .def("append", &ProjectCollection::append, py::arg("item"))
        .def("remove", &ProjectCollection::remove, py::arg("item"));

}

void bindFolderItem(py::module_& m)
{
    py::class_<FolderItem, Item, std::shared_ptr<FolderItem>>(m, "FolderItem")
        .def(py::init(&FolderItem::createNew), py::arg("name") = "New Folder")
        .def_property_readonly("children", &FolderItem::ChildItems, py::return_value_policy::reference);

}

void bindAdjustmentLayerItem(py::module_& m)
{
    py::class_<AdjustmentLayer, Layer, std::shared_ptr<AdjustmentLayer>>(m, "AdjustmentLayer")
        //takes compitem and name as args
        .def(py::init(&AdjustmentLayer::createNew), py::arg("comp"), py::arg("name") = "Adjustment Layer");
}

void bindProject(py::module_& m)
{
    py::class_<Project, std::shared_ptr<Project>>(m, "Project")
        .def(py::init<>())
        .def_property_readonly("activeItem", &Project::ActiveItem, py::return_value_policy::reference)
        .def_property_readonly("activeLayer", &Project::GetActiveLayer, py::return_value_policy::reference)
        .def_property_readonly("name", &Project::getName)
        .def_property_readonly("path", &Project::getPath)
        .def_property_readonly("items", &Project::ChildItems, py::return_value_policy::reference)
        .def_property_readonly("selectedItems", &Project::SelectedItems, py::return_value_policy::reference) //add to docs
        .def("saveAs", &Project::saveAs, py::arg("path"));

}

void bindApp(py::module_& m)
{

    py::class_<App, std::shared_ptr<App>>(m, "App")
        .def(py::init<>())
        .def_property_readonly("path", &App::pluginPaths)
        .def_property_readonly("project", &App::getProject)
        .def("beginUndoGroup", &App::beginUndoGroup, py::arg("undo_name") = "Default Undo Group Name")
        .def("endUndoGroup", &App::endUndoGroup)
        .def("reportInfo", [](App& self, py::object info) {
        std::string infoStr = py::str(info); // Convert any Python object to a string
        self.reportInfo(infoStr);
            }, py::arg("info"))
        .def("executeScript", &App::executeScript, py::arg("script"),
            py::call_guard<py::gil_scoped_release>());
    // Create an instance of App and set it as an attribute of the module
    auto appInstance = std::make_shared<App>();
    m.attr("app") = appInstance;

}

void bindStreamUtils(py::module_& m)
{
    // Enable a Layer Style by navigating: layer root → "ADBE Layer Styles" → style matchname
    // Then set AEGP_DynStreamFlag_ACTIVE_EYEBALL
    // Usage: psc.enable_layer_style(layer, "dropShadow/enabled", True)
    m.def("enable_layer_style", [](std::shared_ptr<Layer> layer,
                                    const std::string& styleMatchname,
                                    bool enabled) -> std::string {
        auto layerH = layer->getLayerHandle();

        // Step 1: Get layer root stream
        auto& msg1 = enqueueSyncTaskQuiet(getNewStreamRefForLayer, layerH);
        msg1->wait();
        auto rootStream = msg1->getResult();
        if (rootStream.error != A_Err_NONE || rootStream.value == NULL)
            return "ERR:cannot_get_layer_root";

        // Step 2: Navigate to "ADBE Layer Styles" group
        auto& msg2 = enqueueSyncTaskQuiet(getNewStreamByMatchname, rootStream, std::string("ADBE Layer Styles"));
        msg2->wait();
        auto lsStream = msg2->getResult();
        if (lsStream.error != A_Err_NONE || lsStream.value == NULL) {
            enqueueSyncTaskQuiet(disposeStream, rootStream)->wait();
            return "ERR:no_layer_styles_group";
        }

        // Step 3: Navigate to specific style (e.g. "dropShadow/enabled")
        auto& msg3 = enqueueSyncTaskQuiet(getNewStreamByMatchname, lsStream, styleMatchname);
        msg3->wait();
        auto styleStream = msg3->getResult();
        if (styleStream.error != A_Err_NONE || styleStream.value == NULL) {
            enqueueSyncTaskQuiet(disposeStream, lsStream)->wait();
            enqueueSyncTaskQuiet(disposeStream, rootStream)->wait();
            return "ERR:style_not_found:" + styleMatchname;
        }

        // Step 4: Set ACTIVE_EYEBALL flag (undoable)
        auto& msg4 = enqueueSyncTaskQuiet(setDynamicStreamFlag, styleStream,
            (AEGP_DynStreamFlags)0x1,  // AEGP_DynStreamFlag_ACTIVE_EYEBALL
            (A_Boolean)TRUE, (A_Boolean)(enabled ? TRUE : FALSE));
        msg4->wait();
        auto flagResult = msg4->getResult();

        // Cleanup
        enqueueSyncTaskQuiet(disposeStream, styleStream)->wait();
        enqueueSyncTaskQuiet(disposeStream, lsStream)->wait();
        enqueueSyncTaskQuiet(disposeStream, rootStream)->wait();

        if (flagResult.error != A_Err_NONE)
            return "ERR:set_flag_failed:" + std::to_string(flagResult.error);

        return "ok";
    }, py::arg("layer"), py::arg("style"), py::arg("enabled"),
       py::call_guard<py::gil_scoped_release>());

    // Generic: set any dynamic stream flag on a property via matchname path
    // Usage: psc.set_stream_flag(layer, ["ADBE Layer Styles", "dropShadow/enabled"], flag, set)
    m.def("set_stream_flag", [](std::shared_ptr<Layer> layer,
                                 const std::vector<std::string>& path,
                                 int flag, bool set) -> std::string {
        auto layerH = layer->getLayerHandle();

        auto& msg1 = enqueueSyncTaskQuiet(getNewStreamRefForLayer, layerH);
        msg1->wait();
        auto current = msg1->getResult();
        if (current.error != A_Err_NONE || current.value == NULL)
            return "ERR:cannot_get_layer_root";

        std::vector<Result<AEGP_StreamRefH>> toDispose;
        toDispose.push_back(current);

        // Navigate path
        for (const auto& mn : path) {
            auto& msg = enqueueSyncTaskQuiet(getNewStreamByMatchname, current, mn);
            msg->wait();
            current = msg->getResult();
            if (current.error != A_Err_NONE || current.value == NULL) {
                for (auto& s : toDispose) enqueueSyncTaskQuiet(disposeStream, s)->wait();
                return "ERR:path_not_found:" + mn;
            }
            toDispose.push_back(current);
        }

        // Set flag
        auto& msgFlag = enqueueSyncTaskQuiet(setDynamicStreamFlag, current,
            (AEGP_DynStreamFlags)flag, (A_Boolean)TRUE, (A_Boolean)(set ? TRUE : FALSE));
        msgFlag->wait();
        auto result = msgFlag->getResult();

        // Cleanup all streams
        for (auto it = toDispose.rbegin(); it != toDispose.rend(); ++it)
            enqueueSyncTaskQuiet(disposeStream, *it)->wait();

        if (result.error != A_Err_NONE)
            return "ERR:set_flag_failed:" + std::to_string(result.error);
        return "ok";
    }, py::arg("layer"), py::arg("path"), py::arg("flag"), py::arg("set"),
       py::call_guard<py::gil_scoped_release>());

    // ── Force UI Refresh ──
    // Force AE to process pending changes (via PostMessage to wake event loop)
    m.def("refresh_ui", []() -> std::string {
#ifdef AE_OS_WIN
        HWND aeWnd = FindWindowW(L"AE_CApplication_26.1", NULL);
        if (!aeWnd) aeWnd = FindWindowW(L"AE_CApplication_25.0", NULL);
        if (aeWnd) PostMessageW(aeWnd, WM_NULL, 0, 0);
        return "ok";
#else
        return "ok";
#endif
    });

    // ── Get Stream Value by matchname path (native, no JSX) ──
    // Usage: psc.get_stream_value(layer, ["ADBE Effect Parade", "ADBE Gaussian Blur 2", "ADBE Gaussian Blur 2-0001"], time)
    // Returns: list of floats (1D→[v], 2D→[x,y], 3D→[x,y,z], color→[r,g,b,a])
    m.def("get_stream_value", [](std::shared_ptr<Layer> layer,
                                  const std::vector<std::string>& path,
                                  float time) -> py::object {
        enum class ValueKind {
            Error,
            Scalar,
            Vector
        };

        ValueKind kind = ValueKind::Error;
        std::string error;
        double scalar = 0.0;
        std::vector<double> values;

        {
            py::gil_scoped_release release;

            auto layerH = layer->getLayerHandle();

            auto& msg1 = enqueueSyncTaskQuiet(getNewStreamRefForLayer, layerH);
            msg1->wait();
            auto current = msg1->getResult();
            if (current.error != A_Err_NONE || current.value == NULL) {
                error = "ERR:cannot_get_layer_root";
            } else {
                std::vector<Result<AEGP_StreamRefH>> toDispose;
                toDispose.push_back(current);

                for (const auto& mn : path) {
                    auto& msg = enqueueSyncTaskQuiet(getNewStreamByMatchname, current, mn);
                    msg->wait();
                    current = msg->getResult();
                    if (current.error != A_Err_NONE || current.value == NULL) {
                        error = "ERR:path_not_found:" + mn;
                        break;
                    }
                    toDispose.push_back(current);
                }

                if (error.empty()) {
                    A_Time timeT;
                    timeT.value = static_cast<A_long>(time * 1000000);
                    timeT.scale = 1000000;

                    auto& msgVal = enqueueSyncTaskQuiet(getNewStreamValue, current,
                        AEGP_LTimeMode_CompTime, timeT, (A_Boolean)FALSE);
                    msgVal->wait();
                    auto valResult = msgVal->getResult();

                    auto& msgType = enqueueSyncTaskQuiet(getStreamType, current);
                    msgType->wait();
                    auto typeResult = msgType->getResult();

                    if (valResult.error == A_Err_NONE) {
                        AEGP_StreamType sType = typeResult.value;
                        AEGP_StreamVal2& v = valResult.value.val;
                        switch (sType) {
                            case AEGP_StreamType_OneD:
                                kind = ValueKind::Scalar;
                                scalar = v.one_d;
                                break;
                            case AEGP_StreamType_TwoD:
                            case AEGP_StreamType_TwoD_SPATIAL:
                                kind = ValueKind::Vector;
                                values = { v.two_d.x, v.two_d.y };
                                break;
                            case AEGP_StreamType_ThreeD:
                            case AEGP_StreamType_ThreeD_SPATIAL:
                                kind = ValueKind::Vector;
                                values = { v.three_d.x, v.three_d.y, v.three_d.z };
                                break;
                            case AEGP_StreamType_COLOR:
                                kind = ValueKind::Vector;
                                values = { v.color.redF, v.color.greenF, v.color.blueF, v.color.alphaF };
                                break;
                            default:
                                error = "unsupported_type:" + std::to_string(sType);
                                break;
                        }
                        enqueueSyncTaskQuiet(disposeStreamValue, &valResult.value)->wait();
                    } else {
                        error = "ERR:get_value_failed:" + std::to_string(valResult.error);
                    }
                }

                for (auto it = toDispose.rbegin(); it != toDispose.rend(); ++it) {
                    enqueueSyncTaskQuiet(disposeStream, *it)->wait();
                }
            }
        }

        if (!error.empty()) {
            return py::cast(error);
        }
        if (kind == ValueKind::Scalar) {
            return py::cast(scalar);
        }
        return py::cast(values);
    }, py::arg("layer"), py::arg("path"), py::arg("time"));

    // ── List child streams (enumerate property tree) ──
    // Usage: psc.list_streams(layer, ["ADBE Effect Parade"]) → [{"index":0,"matchName":"...","name":"..."}, ...]
    m.def("list_streams", [](std::shared_ptr<Layer> layer,
                              const std::vector<std::string>& path) -> py::object {
        struct StreamInfo {
            int index;
            int type;
            int numChildren;
            int groupType;
            std::string name;
            std::string matchName;
        };

        std::string error;
        std::vector<StreamInfo> infos;

        {
            py::gil_scoped_release release;

            auto layerH = layer->getLayerHandle();
            auto collect_stream_info = [&](int index, const Result<AEGP_StreamRefH>& stream) {
                auto& msgType = enqueueSyncTaskQuiet(getStreamType, stream);
                msgType->wait();
                auto typeResult = msgType->getResult();

                auto& msgGroup = enqueueSyncTaskQuiet(getStreamGroupingType, stream);
                msgGroup->wait();
                auto groupResult = msgGroup->getResult();

                int numChildren = 0;
                if (groupResult.error == A_Err_NONE &&
                    (groupResult.value == AEGP_StreamGroupingType_NAMED_GROUP ||
                     groupResult.value == AEGP_StreamGroupingType_INDEXED_GROUP)) {
                    auto& msgNum = enqueueSyncTaskQuiet(getNumStreamsInGroup, stream);
                    msgNum->wait();
                    auto numResult = msgNum->getResult();
                    if (numResult.error == A_Err_NONE) {
                        numChildren = numResult.value;
                    }
                }

                auto& msgName = enqueueSyncTaskQuiet(getStreamName, stream, false);
                msgName->wait();
                auto nameResult = msgName->getResult();

                auto& msgMatch = enqueueSyncTaskQuiet(getStreamMatchName, stream);
                msgMatch->wait();
                auto matchResult = msgMatch->getResult();

                infos.push_back(StreamInfo{
                    index,
                    typeResult.error == A_Err_NONE ? static_cast<int>(typeResult.value) : -1,
                    numChildren,
                    groupResult.error == A_Err_NONE ? static_cast<int>(groupResult.value) : static_cast<int>(AEGP_StreamGroupingType_NONE),
                    nameResult.error == A_Err_NONE ? nameResult.value : "",
                    matchResult.error == A_Err_NONE ? matchResult.value : ""
                });
            };

            if (path.empty()) {
                for (int which = AEGP_LayerStream_BEGIN; which < AEGP_LayerStream_END; ++which) {
                    auto layerStream = static_cast<AEGP_LayerStream>(which);
                    auto& msgLegal = enqueueSyncTaskQuiet(isStreamLegal, layerH, layerStream);
                    msgLegal->wait();
                    auto legalResult = msgLegal->getResult();
                    if (legalResult.error != A_Err_NONE || !legalResult.value) {
                        continue;
                    }

                    auto& msgStream = enqueueSyncTaskQuiet(getNewLayerStream, layerH, layerStream);
                    msgStream->wait();
                    auto streamResult = msgStream->getResult();
                    if (streamResult.error == A_Err_NONE && streamResult.value != NULL) {
                        collect_stream_info(which, streamResult);
                        enqueueSyncTaskQuiet(disposeStream, streamResult)->wait();
                    }
                }
            } else {
                auto& msg1 = enqueueSyncTaskQuiet(getNewStreamRefForLayer, layerH);
                msg1->wait();
                auto current = msg1->getResult();
                if (current.error != A_Err_NONE || current.value == NULL) {
                    error = "ERR:cannot_get_layer_root";
                } else {
                    std::vector<Result<AEGP_StreamRefH>> toDispose;
                    toDispose.push_back(current);

                    for (const auto& mn : path) {
                        auto& msg = enqueueSyncTaskQuiet(getNewStreamByMatchname, current, mn);
                        msg->wait();
                        current = msg->getResult();
                        if (current.error != A_Err_NONE || current.value == NULL) {
                            error = "ERR:path_not_found:" + mn;
                            break;
                        }
                        toDispose.push_back(current);
                    }

                    if (error.empty()) {
                        auto& msgGroup = enqueueSyncTaskQuiet(getStreamGroupingType, current);
                        msgGroup->wait();
                        auto groupResult = msgGroup->getResult();
                        if (groupResult.error != A_Err_NONE) {
                            error = "ERR:cannot_get_group_type";
                        } else if (groupResult.value != AEGP_StreamGroupingType_NAMED_GROUP &&
                                   groupResult.value != AEGP_StreamGroupingType_INDEXED_GROUP) {
                            error = "ERR:not_a_group";
                        } else {
                            auto& msgNum = enqueueSyncTaskQuiet(getNumStreamsInGroup, current);
                            msgNum->wait();
                            auto numResult = msgNum->getResult();
                            if (numResult.error != A_Err_NONE) {
                                error = "ERR:cannot_get_children";
                            } else {
                                for (int i = 0; i < numResult.value; i++) {
                                    auto& msgChild = enqueueSyncTaskQuiet(getNewStreamByIndex, current, i);
                                    msgChild->wait();
                                    auto child = msgChild->getResult();
                                    if (child.error == A_Err_NONE && child.value != NULL) {
                                        collect_stream_info(i, child);
                                        enqueueSyncTaskQuiet(disposeStream, child)->wait();
                                    }
                                }
                            }
                        }
                    }

                    for (auto it = toDispose.rbegin(); it != toDispose.rend(); ++it) {
                        enqueueSyncTaskQuiet(disposeStream, *it)->wait();
                    }
                }
            }
        }

        if (!error.empty()) {
            return py::cast(error);
        }

        py::list result;
        for (const auto& info : infos) {
            py::dict item;
            item["index"] = info.index;
            item["type"] = info.type;
            item["numChildren"] = info.numChildren;
            item["groupType"] = info.groupType;
            item["name"] = info.name;
            item["matchName"] = info.matchName;
            result.append(item);
        }
        return result;
    }, py::arg("layer"), py::arg("path"));

    // ── Unhide all children of a property group ──
    // Useful for Essential Properties, hidden effect params, etc.
    m.def("unhide_stream_children", [](std::shared_ptr<Layer> layer,
                                        const std::vector<std::string>& path) -> std::string {
        auto layerH = layer->getLayerHandle();

        auto& msg1 = enqueueSyncTaskQuiet(getNewStreamRefForLayer, layerH);
        msg1->wait();
        auto current = msg1->getResult();
        if (current.error != A_Err_NONE || current.value == NULL)
            return "ERR:cannot_get_layer_root";

        std::vector<Result<AEGP_StreamRefH>> toDispose;
        toDispose.push_back(current);

        for (const auto& mn : path) {
            auto& msg = enqueueSyncTaskQuiet(getNewStreamByMatchname, current, mn);
            msg->wait();
            current = msg->getResult();
            if (current.error != A_Err_NONE || current.value == NULL) {
                for (auto& s : toDispose) enqueueSyncTaskQuiet(disposeStream, s)->wait();
                return "ERR:path_not_found:" + mn;
            }
            toDispose.push_back(current);
        }

        // Unhide parent
        enqueueSyncTaskQuiet(setDynamicStreamFlag, current,
            (AEGP_DynStreamFlags)0x2, (A_Boolean)TRUE, (A_Boolean)FALSE)->wait();

        // Unhide all children
        auto& msgNum = enqueueSyncTaskQuiet(getNumStreamsInGroup, current);
        msgNum->wait();
        int numChildren = msgNum->getResult().value;

        int unhidden = 0;
        for (int i = 0; i < numChildren; i++) {
            auto& msgChild = enqueueSyncTaskQuiet(getNewStreamByIndex, current, i);
            msgChild->wait();
            auto child = msgChild->getResult();
            if (child.error == A_Err_NONE && child.value != NULL) {
                enqueueSyncTaskQuiet(setDynamicStreamFlag, child,
                    (AEGP_DynStreamFlags)0x2, (A_Boolean)TRUE, (A_Boolean)FALSE)->wait();
                unhidden++;
                enqueueSyncTaskQuiet(disposeStream, child)->wait();
            }
        }

        for (auto it = toDispose.rbegin(); it != toDispose.rend(); ++it)
            enqueueSyncTaskQuiet(disposeStream, *it)->wait();

        return "ok:unhidden=" + std::to_string(unhidden);
    }, py::arg("layer"), py::arg("path"),
       py::call_guard<py::gil_scoped_release>());

    // ── Native keyframe count on a stream path ──
    m.def("get_stream_keyframe_count", [](std::shared_ptr<Layer> layer,
                                           const std::vector<std::string>& path) -> int {
        auto layerH = layer->getLayerHandle();

        auto& msg1 = enqueueSyncTaskQuiet(getNewStreamRefForLayer, layerH);
        msg1->wait();
        auto current = msg1->getResult();
        if (current.error != A_Err_NONE || current.value == NULL) return -1;

        std::vector<Result<AEGP_StreamRefH>> toDispose;
        toDispose.push_back(current);

        for (const auto& mn : path) {
            auto& msg = enqueueSyncTaskQuiet(getNewStreamByMatchname, current, mn);
            msg->wait();
            current = msg->getResult();
            if (current.error != A_Err_NONE || current.value == NULL) {
                for (auto& s : toDispose) enqueueSyncTaskQuiet(disposeStream, s)->wait();
                return -1;
            }
            toDispose.push_back(current);
        }

        auto& msgKF = enqueueSyncTaskQuiet(getStreamNumKFs, current);
        msgKF->wait();
        int count = msgKF->getResult().value;

        for (auto it = toDispose.rbegin(); it != toDispose.rend(); ++it)
            enqueueSyncTaskQuiet(disposeStream, *it)->wait();

        return count;
    }, py::arg("layer"), py::arg("path"),
       py::call_guard<py::gil_scoped_release>());

    // ── Native Keyframe Insert ──
    m.def("insert_keyframe", [](std::shared_ptr<Layer> layer,
                                 const std::vector<std::string>& path,
                                 float time) -> int {
        auto layerH = layer->getLayerHandle();
        auto& msg1 = enqueueSyncTaskQuiet(getNewStreamRefForLayer, layerH);
        msg1->wait();
        auto current = msg1->getResult();
        if (current.error != A_Err_NONE || current.value == NULL) return -1;

        std::vector<Result<AEGP_StreamRefH>> toDispose;
        toDispose.push_back(current);

        for (const auto& mn : path) {
            auto& msg = enqueueSyncTaskQuiet(getNewStreamByMatchname, current, mn);
            msg->wait();
            current = msg->getResult();
            if (current.error != A_Err_NONE || current.value == NULL) {
                for (auto& s : toDispose) enqueueSyncTaskQuiet(disposeStream, s)->wait();
                return -1;
            }
            toDispose.push_back(current);
        }

        A_Time timeT;
        timeT.value = static_cast<A_long>(time * 1000000);
        timeT.scale = 1000000;

        auto& msgKF = enqueueSyncTaskQuiet(insertKeyframe, current, AEGP_LTimeMode_CompTime, timeT);
        msgKF->wait();
        int newIndex = msgKF->getResult().value;

        for (auto it = toDispose.rbegin(); it != toDispose.rend(); ++it)
            enqueueSyncTaskQuiet(disposeStream, *it)->wait();

        return newIndex;
    }, py::arg("layer"), py::arg("path"), py::arg("time"),
       py::call_guard<py::gil_scoped_release>());

    // ── Native Keyframe Delete ──
    m.def("delete_keyframe", [](std::shared_ptr<Layer> layer,
                                 const std::vector<std::string>& path,
                                 int kf_index) -> std::string {
        auto layerH = layer->getLayerHandle();
        auto& msg1 = enqueueSyncTaskQuiet(getNewStreamRefForLayer, layerH);
        msg1->wait();
        auto current = msg1->getResult();
        if (current.error != A_Err_NONE || current.value == NULL) return "ERR:no_root";

        std::vector<Result<AEGP_StreamRefH>> toDispose;
        toDispose.push_back(current);

        for (const auto& mn : path) {
            auto& msg = enqueueSyncTaskQuiet(getNewStreamByMatchname, current, mn);
            msg->wait();
            current = msg->getResult();
            if (current.error != A_Err_NONE || current.value == NULL) {
                for (auto& s : toDispose) enqueueSyncTaskQuiet(disposeStream, s)->wait();
                return "ERR:path_not_found";
            }
            toDispose.push_back(current);
        }

        auto& msgDel = enqueueSyncTaskQuiet(deleteKeyframe, current, kf_index);
        msgDel->wait();
        auto result = msgDel->getResult();

        for (auto it = toDispose.rbegin(); it != toDispose.rend(); ++it)
            enqueueSyncTaskQuiet(disposeStream, *it)->wait();

        return result.error == A_Err_NONE ? "ok" : "ERR:" + std::to_string(result.error);
    }, py::arg("layer"), py::arg("path"), py::arg("kf_index"),
       py::call_guard<py::gil_scoped_release>());

    // ── Set Keyframe Interpolation ──
    m.def("set_keyframe_interpolation", [](std::shared_ptr<Layer> layer,
                                            const std::vector<std::string>& path,
                                            int kf_index,
                                            int in_type, int out_type) -> std::string {
        auto layerH = layer->getLayerHandle();
        auto& msg1 = enqueueSyncTaskQuiet(getNewStreamRefForLayer, layerH);
        msg1->wait();
        auto current = msg1->getResult();
        if (current.error != A_Err_NONE || current.value == NULL) return "ERR:no_root";

        std::vector<Result<AEGP_StreamRefH>> toDispose;
        toDispose.push_back(current);

        for (const auto& mn : path) {
            auto& msg = enqueueSyncTaskQuiet(getNewStreamByMatchname, current, mn);
            msg->wait();
            current = msg->getResult();
            if (current.error != A_Err_NONE || current.value == NULL) {
                for (auto& s : toDispose) enqueueSyncTaskQuiet(disposeStream, s)->wait();
                return "ERR:path_not_found";
            }
            toDispose.push_back(current);
        }

        auto& msgInterp = enqueueSyncTaskQuiet(setKeyframeInterpolation, current, kf_index,
            static_cast<AEGP_KeyframeInterpolationType>(in_type),
            static_cast<AEGP_KeyframeInterpolationType>(out_type));
        msgInterp->wait();
        auto result = msgInterp->getResult();

        for (auto it = toDispose.rbegin(); it != toDispose.rend(); ++it)
            enqueueSyncTaskQuiet(disposeStream, *it)->wait();

        return result.error == A_Err_NONE ? "ok" : "ERR:" + std::to_string(result.error);
    }, py::arg("layer"), py::arg("path"), py::arg("kf_index"),
       py::arg("in_type"), py::arg("out_type"),
       py::call_guard<py::gil_scoped_release>());

    // ── Helper: navigate path from layer root, returns (stream, toDispose) ──
    // (shared logic extracted as a C++ lambda for reuse below)

    // ── Get Keyframe Value (native) ──
    // Returns: float (1D), list[float] (2D/3D/color), or error string
    m.def("get_keyframe_value", [](std::shared_ptr<Layer> layer,
                                    const std::vector<std::string>& path,
                                    int kf_index) -> py::object {
        enum class ValueKind {
            Error,
            Scalar,
            Vector
        };

        ValueKind kind = ValueKind::Error;
        std::string error;
        double scalar = 0.0;
        std::vector<double> values;

        {
            py::gil_scoped_release release;

            auto layerH = layer->getLayerHandle();
            auto& msg1 = enqueueSyncTaskQuiet(getNewStreamRefForLayer, layerH);
            msg1->wait();
            auto current = msg1->getResult();
            if (current.error != A_Err_NONE || current.value == NULL) {
                error = "ERR:no_root";
            } else {
                std::vector<Result<AEGP_StreamRefH>> toDispose;
                toDispose.push_back(current);

                for (const auto& mn : path) {
                    auto& msg = enqueueSyncTaskQuiet(getNewStreamByMatchname, current, mn);
                    msg->wait();
                    current = msg->getResult();
                    if (current.error != A_Err_NONE || current.value == NULL) {
                        error = "ERR:path_not_found:" + mn;
                        break;
                    }
                    toDispose.push_back(current);
                }

                if (error.empty()) {
                    auto& msgType = enqueueSyncTaskQuiet(getStreamType, current);
                    msgType->wait();
                    AEGP_StreamType sType = msgType->getResult().value;

                    auto& msgKV = enqueueSyncTaskQuiet(getKeyframeValue, current, kf_index);
                    msgKV->wait();
                    auto kvResult = msgKV->getResult();

                    if (kvResult.error == A_Err_NONE) {
                        AEGP_StreamVal2& v = kvResult.value.val;
                        switch (sType) {
                            case AEGP_StreamType_OneD:
                                kind = ValueKind::Scalar;
                                scalar = v.one_d;
                                break;
                            case AEGP_StreamType_TwoD:
                            case AEGP_StreamType_TwoD_SPATIAL:
                                kind = ValueKind::Vector;
                                values = { v.two_d.x, v.two_d.y };
                                break;
                            case AEGP_StreamType_ThreeD:
                            case AEGP_StreamType_ThreeD_SPATIAL:
                                kind = ValueKind::Vector;
                                values = { v.three_d.x, v.three_d.y, v.three_d.z };
                                break;
                            case AEGP_StreamType_COLOR:
                                kind = ValueKind::Vector;
                                values = { v.color.redF, v.color.greenF, v.color.blueF, v.color.alphaF };
                                break;
                            default:
                                error = "unsupported_type";
                                break;
                        }
                        enqueueSyncTaskQuiet(disposeStreamValue, &kvResult.value)->wait();
                    } else {
                        error = "ERR:" + std::to_string(kvResult.error);
                    }
                }

                for (auto it = toDispose.rbegin(); it != toDispose.rend(); ++it) {
                    enqueueSyncTaskQuiet(disposeStream, *it)->wait();
                }
            }
        }

        if (!error.empty()) {
            return py::cast(error);
        }
        if (kind == ValueKind::Scalar) {
            return py::cast(scalar);
        }
        return py::cast(values);
    }, py::arg("layer"), py::arg("path"), py::arg("kf_index"));

    // ── Get Keyframe Time (native) ──
    m.def("get_keyframe_time", [](std::shared_ptr<Layer> layer,
                                   const std::vector<std::string>& path,
                                   int kf_index) -> float {
        auto layerH = layer->getLayerHandle();
        auto& msg1 = enqueueSyncTaskQuiet(getNewStreamRefForLayer, layerH);
        msg1->wait();
        auto current = msg1->getResult();
        if (current.error != A_Err_NONE || current.value == NULL) return -1.0f;

        std::vector<Result<AEGP_StreamRefH>> toDispose;
        toDispose.push_back(current);

        for (const auto& mn : path) {
            auto& msg = enqueueSyncTaskQuiet(getNewStreamByMatchname, current, mn);
            msg->wait();
            current = msg->getResult();
            if (current.error != A_Err_NONE || current.value == NULL) {
                for (auto& s : toDispose) enqueueSyncTaskQuiet(disposeStream, s)->wait();
                return -1.0f;
            }
            toDispose.push_back(current);
        }

        auto& msgKT = enqueueSyncTaskQuiet(getKeyframeTime, current, kf_index, AEGP_LTimeMode_CompTime);
        msgKT->wait();
        A_Time t = msgKT->getResult().value;
        float result = (t.scale != 0) ? static_cast<float>(t.value) / static_cast<float>(t.scale) : 0.0f;

        for (auto it = toDispose.rbegin(); it != toDispose.rend(); ++it)
            enqueueSyncTaskQuiet(disposeStream, *it)->wait();
        return result;
    }, py::arg("layer"), py::arg("path"), py::arg("kf_index"),
       py::call_guard<py::gil_scoped_release>());

    // ── Set Keyframe Temporal Ease (native) ──
    // ease: [speed, influence] per dimension
    m.def("set_keyframe_ease", [](std::shared_ptr<Layer> layer,
                                   const std::vector<std::string>& path,
                                   int kf_index,
                                   float in_speed, float in_influence,
                                   float out_speed, float out_influence,
                                   int num_dims) -> std::string {
        auto layerH = layer->getLayerHandle();
        auto& msg1 = enqueueSyncTaskQuiet(getNewStreamRefForLayer, layerH);
        msg1->wait();
        auto current = msg1->getResult();
        if (current.error != A_Err_NONE || current.value == NULL) return "ERR:no_root";

        std::vector<Result<AEGP_StreamRefH>> toDispose;
        toDispose.push_back(current);

        for (const auto& mn : path) {
            auto& msg = enqueueSyncTaskQuiet(getNewStreamByMatchname, current, mn);
            msg->wait();
            current = msg->getResult();
            if (current.error != A_Err_NONE || current.value == NULL) {
                for (auto& s : toDispose) enqueueSyncTaskQuiet(disposeStream, s)->wait();
                return "ERR:path_not_found";
            }
            toDispose.push_back(current);
        }

        // Create ease arrays (same ease for all dims)
        std::vector<AEGP_KeyframeEase> inEase(num_dims);
        std::vector<AEGP_KeyframeEase> outEase(num_dims);
        for (int i = 0; i < num_dims; i++) {
            inEase[i].speedF = in_speed;
            inEase[i].influenceF = in_influence;
            outEase[i].speedF = out_speed;
            outEase[i].influenceF = out_influence;
        }

        auto& msgEase = enqueueSyncTaskQuiet(setKeyframeTemporalEase, current, kf_index,
            static_cast<A_long>(num_dims), inEase.data(), outEase.data());
        msgEase->wait();
        auto result = msgEase->getResult();

        for (auto it = toDispose.rbegin(); it != toDispose.rend(); ++it)
            enqueueSyncTaskQuiet(disposeStream, *it)->wait();

        return result.error == A_Err_NONE ? "ok" : "ERR:" + std::to_string(result.error);
    }, py::arg("layer"), py::arg("path"), py::arg("kf_index"),
       py::arg("in_speed"), py::arg("in_influence"),
       py::arg("out_speed"), py::arg("out_influence"),
       py::arg("num_dims") = 1,
       py::call_guard<py::gil_scoped_release>());

    // ── Get Expression (native) ──
    m.def("get_expression", [](std::shared_ptr<Layer> layer,
                                const std::vector<std::string>& path) -> std::string {
        auto layerH = layer->getLayerHandle();
        auto& msg1 = enqueueSyncTaskQuiet(getNewStreamRefForLayer, layerH);
        msg1->wait();
        auto current = msg1->getResult();
        if (current.error != A_Err_NONE || current.value == NULL) return "ERR:no_root";

        std::vector<Result<AEGP_StreamRefH>> toDispose;
        toDispose.push_back(current);

        for (const auto& mn : path) {
            auto& msg = enqueueSyncTaskQuiet(getNewStreamByMatchname, current, mn);
            msg->wait();
            current = msg->getResult();
            if (current.error != A_Err_NONE || current.value == NULL) {
                for (auto& s : toDispose) enqueueSyncTaskQuiet(disposeStream, s)->wait();
                return "ERR:path_not_found:" + mn;
            }
            toDispose.push_back(current);
        }

        auto& msgExpr = enqueueSyncTaskQuiet(getExpression, current);
        msgExpr->wait();
        std::string expr = msgExpr->getResult().value;

        for (auto it = toDispose.rbegin(); it != toDispose.rend(); ++it)
            enqueueSyncTaskQuiet(disposeStream, *it)->wait();
        return expr;
    }, py::arg("layer"), py::arg("path"),
       py::call_guard<py::gil_scoped_release>());

    // ── Set Expression (native) ──
    m.def("set_expression", [](std::shared_ptr<Layer> layer,
                                const std::vector<std::string>& path,
                                const std::string& expr) -> std::string {
        auto layerH = layer->getLayerHandle();
        auto& msg1 = enqueueSyncTaskQuiet(getNewStreamRefForLayer, layerH);
        msg1->wait();
        auto current = msg1->getResult();
        if (current.error != A_Err_NONE || current.value == NULL) return "ERR:no_root";

        std::vector<Result<AEGP_StreamRefH>> toDispose;
        toDispose.push_back(current);

        for (const auto& mn : path) {
            auto& msg = enqueueSyncTaskQuiet(getNewStreamByMatchname, current, mn);
            msg->wait();
            current = msg->getResult();
            if (current.error != A_Err_NONE || current.value == NULL) {
                for (auto& s : toDispose) enqueueSyncTaskQuiet(disposeStream, s)->wait();
                return "ERR:path_not_found:" + mn;
            }
            toDispose.push_back(current);
        }

        auto& msgSet = enqueueSyncTaskQuiet(setExpression, current, expr);
        msgSet->wait();
        auto result = msgSet->getResult();

        for (auto it = toDispose.rbegin(); it != toDispose.rend(); ++it)
            enqueueSyncTaskQuiet(disposeStream, *it)->wait();

        return result.error == A_Err_NONE ? "ok" : "ERR:" + std::to_string(result.error);
    }, py::arg("layer"), py::arg("path"), py::arg("expr"),
       py::call_guard<py::gil_scoped_release>());

    // ══════════════════════════════════════════════════════════
    // ── Effect Native Operations (bypass JSX) ──
    // ══════════════════════════════════════════════════════════

    // ── Get number of effects on layer ──
    m.def("get_layer_num_effects", [](std::shared_ptr<Layer> layer) -> int {
        auto& msg = enqueueSyncTaskQuiet(GetLayerNumEffects, layer->getLayerHandle());
        msg->wait();
        auto result = msg->getResult();
        if (result.error != A_Err_NONE) {
            throw std::runtime_error("Error getting number of effects: " + std::to_string(result.error));
        }
        return result.value;
    }, py::arg("layer"),
       py::call_guard<py::gil_scoped_release>());

    // ── Get effect matchName by index ──
    m.def("get_effect_matchname", [](std::shared_ptr<Layer> layer, int index) -> std::string {
        auto& msg1 = enqueueSyncTaskQuiet(GetLayerEffectByIndex, layer->getLayerHandle(), index);
        msg1->wait();
        auto effectH = msg1->getResult();
        if (effectH.error != A_Err_NONE || effectH.value == NULL) return "ERR:no_effect";

        auto& msg2 = enqueueSyncTaskQuiet(GetInstalledKeyFromLayerEffect, effectH);
        msg2->wait();
        auto key = msg2->getResult();

        auto& msg3 = enqueueSyncTaskQuiet(GetEffectMatchName, key);
        msg3->wait();
        std::string mn = msg3->getResult().value;

        enqueueSyncTaskQuiet(DisposeEffect, effectH)->wait();
        return mn;
    }, py::arg("layer"), py::arg("index"),
       py::call_guard<py::gil_scoped_release>());

    // ── Apply effect by matchName (native) ──
    // Returns effect index or -1
    m.def("apply_effect", [](std::shared_ptr<Layer> layer,
                              const std::string& matchName) -> int {
        auto& msgApply = enqueueSyncTaskQuiet(ApplyEffectByMatchName, layer->getLayerHandle(), matchName);
        msgApply->wait();
        auto result = msgApply->getResult();
        if (result.error != A_Err_NONE) return -2;
        return result.value;
    }, py::arg("layer"), py::arg("matchName"),
       py::call_guard<py::gil_scoped_release>());

    // ── Delete effect by index (native) ──
    m.def("delete_effect", [](std::shared_ptr<Layer> layer, int index) -> std::string {
        auto& msg1 = enqueueSyncTaskQuiet(GetLayerEffectByIndex, layer->getLayerHandle(), index);
        msg1->wait();
        auto effectH = msg1->getResult();
        if (effectH.error != A_Err_NONE || effectH.value == NULL) return "ERR:no_effect";

        auto& msg2 = enqueueSyncTaskQuiet(DeleteLayerEffect, effectH);
        msg2->wait();
        return msg2->getResult().error == A_Err_NONE ? "ok" : "ERR:delete_failed";
    }, py::arg("layer"), py::arg("index"),
       py::call_guard<py::gil_scoped_release>());

    // ── Enable/disable effect by index (native) ──
    m.def("set_effect_enabled", [](std::shared_ptr<Layer> layer, int index, bool enabled) -> std::string {
        auto& msg1 = enqueueSyncTaskQuiet(GetLayerEffectByIndex, layer->getLayerHandle(), index);
        msg1->wait();
        auto effectH = msg1->getResult();
        if (effectH.error != A_Err_NONE || effectH.value == NULL) return "ERR:no_effect";

        // AEGP_EffectFlags: bit 0 = active
        AEGP_EffectFlags mask = 0x1;  // AEGP_EffectFlags_ACTIVE
        AEGP_EffectFlags flags = enabled ? 0x1 : 0x0;
        auto& msg2 = enqueueSyncTaskQuiet(SetEffectFlags, effectH, mask, flags);
        msg2->wait();
        auto result = msg2->getResult();

        enqueueSyncTaskQuiet(DisposeEffect, effectH)->wait();
        return result.error == A_Err_NONE ? "ok" : "ERR:" + std::to_string(result.error);
    }, py::arg("layer"), py::arg("index"), py::arg("enabled"),
       py::call_guard<py::gil_scoped_release>());

    // ── Duplicate effect (native) ──
    m.def("duplicate_effect", [](std::shared_ptr<Layer> layer, int index) -> std::string {
        auto& msg1 = enqueueSyncTaskQuiet(GetLayerEffectByIndex, layer->getLayerHandle(), index);
        msg1->wait();
        auto effectH = msg1->getResult();
        if (effectH.error != A_Err_NONE || effectH.value == NULL) return "ERR:no_effect";

        auto& msg2 = enqueueSyncTaskQuiet(DuplicateEffect, effectH);
        msg2->wait();
        auto newEffect = msg2->getResult();

        enqueueSyncTaskQuiet(DisposeEffect, effectH)->wait();
        if (newEffect.value != NULL) enqueueSyncTaskQuiet(DisposeEffect, newEffect)->wait();

        return newEffect.error == A_Err_NONE ? "ok" : "ERR:" + std::to_string(newEffect.error);
    }, py::arg("layer"), py::arg("index"),
       py::call_guard<py::gil_scoped_release>());

    // ── Reorder effect (native) ──
    m.def("reorder_effect", [](std::shared_ptr<Layer> layer, int from_index, int to_index) -> std::string {
        auto& msg1 = enqueueSyncTaskQuiet(GetLayerEffectByIndex, layer->getLayerHandle(), from_index);
        msg1->wait();
        auto effectH = msg1->getResult();
        if (effectH.error != A_Err_NONE || effectH.value == NULL) return "ERR:no_effect";

        auto& msg2 = enqueueSyncTaskQuiet(ReorderEffect, effectH, to_index);
        msg2->wait();
        auto result = msg2->getResult();

        enqueueSyncTaskQuiet(DisposeEffect, effectH)->wait();
        return result.error == A_Err_NONE ? "ok" : "ERR:" + std::to_string(result.error);
    }, py::arg("layer"), py::arg("from_index"), py::arg("to_index"),
       py::call_guard<py::gil_scoped_release>());

    // ══════════════════════════════════════════════════════════
    // ── Footage Operations (native) ──
    // ══════════════════════════════════════════════════════════

    // ── Replace footage source (batch-friendly) ──
    m.def("replace_footage", [](std::shared_ptr<Item> item,
                                 const std::string& newPath) -> std::string {
        auto itemH = item->getItemHandle();

        // Create new footage from path
        auto& msg1 = enqueueSyncTaskQuiet(createFootage, newPath);
        msg1->wait();
        auto footageH = msg1->getResult();
        if (footageH.error != A_Err_NONE || footageH.value == NULL)
            return "ERR:create_footage_failed";

        // Replace main footage
        auto& msg2 = enqueueSyncTaskQuiet(ReplaceItemMainFootage, footageH, itemH);
        msg2->wait();
        auto result = msg2->getResult();

        return result.error == A_Err_NONE ? "ok" : "ERR:" + std::to_string(result.error);
    }, py::arg("item"), py::arg("path"),
       py::call_guard<py::gil_scoped_release>());

    // ── Get footage file path ──
    m.def("get_footage_path", [](std::shared_ptr<Item> item) -> std::string {
        auto itemH = item->getItemHandle();

        auto& typeMsg = enqueueSyncTaskQuiet(getItemType, itemH);
        typeMsg->wait();
        auto itemType = typeMsg->getResult();
        if (itemType.error != A_Err_NONE)
            return "ERR:cannot_get_item_type";
        if (itemType.value != AEGP_ItemType_FOOTAGE)
            return "ERR:not_footage_item";

        auto& msg1 = enqueueSyncTaskQuiet(GetMainFootageFromItem, itemH);
        msg1->wait();
        auto footageH = msg1->getResult();
        if (footageH.error != A_Err_NONE || footageH.value == NULL)
            return "ERR:no_footage";

        auto& msg2 = enqueueSyncTaskQuiet(GetFootagePath, footageH, 0, 0);
        msg2->wait();
        return msg2->getResult().value;
    }, py::arg("item"),
       py::call_guard<py::gil_scoped_release>());

    // ── Import footage to project ──
    m.def("import_footage", [](const std::string& path, const std::string& folderName) -> std::string {
        auto& msg1 = enqueueSyncTaskQuiet(createFootage, path);
        msg1->wait();
        auto footageH = msg1->getResult();
        if (footageH.error != A_Err_NONE || footageH.value == NULL)
            return "ERR:create_failed";

        auto& msg2 = enqueueSyncTaskQuiet(getProjectRootFolder);
        msg2->wait();
        auto rootH = msg2->getResult();

        auto& msg3 = enqueueSyncTaskQuiet(addFootageToProject, footageH, rootH);
        msg3->wait();
        auto itemH = msg3->getResult();

        return itemH.error == A_Err_NONE ? "ok" : "ERR:" + std::to_string(itemH.error);
    }, py::arg("path"), py::arg("folder") = "",
       py::call_guard<py::gil_scoped_release>());

    // ── Get footage num files (for sequences) ──
    m.def("get_footage_num_files", [](std::shared_ptr<Item> item) -> py::object {
        auto itemH = item->getItemHandle();

        auto& typeMsg = enqueueSyncTaskQuiet(getItemType, itemH);
        typeMsg->wait();
        auto itemType = typeMsg->getResult();
        if (itemType.error != A_Err_NONE || itemType.value != AEGP_ItemType_FOOTAGE)
            return py::cast(-1);

        auto& msg1 = enqueueSyncTaskQuiet(GetMainFootageFromItem, itemH);
        msg1->wait();
        auto footageH = msg1->getResult();
        if (footageH.error != A_Err_NONE) return py::cast(-1);

        auto& msg2 = enqueueSyncTaskQuiet(GetFootageNumFiles, footageH);
        msg2->wait();
        auto result = msg2->getResult();
        return py::cast(std::vector<int>{result.value.first, result.value.second});
    }, py::arg("item"),
       py::call_guard<py::gil_scoped_release>());

    // ══════════════════════════════════════════════════════════
    // ── Item Operations (native) ──
    // ══════════════════════════════════════════════════════════

    // ── Get/Set item parent folder ──
    m.def("get_item_parent_folder", [](std::shared_ptr<Item> item) -> std::string {
        auto& msg = enqueueSyncTaskQuiet(GetItemParentFolder, item->getItemHandle());
        msg->wait();
        auto parentH = msg->getResult();
        if (parentH.error != A_Err_NONE || parentH.value == NULL) return "root";

        auto& msg2 = enqueueSyncTaskQuiet(getItemName, parentH);
        msg2->wait();
        return msg2->getResult().value;
    }, py::arg("item"),
       py::call_guard<py::gil_scoped_release>());

    m.def("set_item_parent_folder", [](std::shared_ptr<Item> item,
                                        std::shared_ptr<Item> folder) -> std::string {
        auto& msg = enqueueSyncTaskQuiet(SetItemParentFolder, item->getItemHandle(), folder->getItemHandle());
        msg->wait();
        return msg->getResult().error == A_Err_NONE ? "ok" : "ERR";
    }, py::arg("item"), py::arg("folder"),
       py::call_guard<py::gil_scoped_release>());

    // ── Get/Set item comment ──
    m.def("get_item_comment", [](std::shared_ptr<Item> item) -> std::string {
        auto& msg = enqueueSyncTaskQuiet(GetItemComment, item->getItemHandle());
        msg->wait();
        return msg->getResult().value;
    }, py::arg("item"),
       py::call_guard<py::gil_scoped_release>());

    m.def("set_item_comment", [](std::shared_ptr<Item> item,
                                  const std::string& comment) -> std::string {
        auto& msg = enqueueSyncTaskQuiet(SetItemComment, item->getItemHandle(), comment);
        msg->wait();
        return msg->getResult().error == A_Err_NONE ? "ok" : "ERR";
    }, py::arg("item"), py::arg("comment"),
       py::call_guard<py::gil_scoped_release>());

    // ── Get/Set item label ──
    m.def("get_item_label", [](std::shared_ptr<Item> item) -> int {
        auto& msg = enqueueSyncTaskQuiet(GetItemLabel, item->getItemHandle());
        msg->wait();
        return static_cast<int>(msg->getResult().value);
    }, py::arg("item"),
       py::call_guard<py::gil_scoped_release>());

    m.def("set_item_label", [](std::shared_ptr<Item> item, int label) -> std::string {
        auto& msg = enqueueSyncTaskQuiet(SetItemLabel, item->getItemHandle(), static_cast<AEGP_LabelID>(label));
        msg->wait();
        return msg->getResult().error == A_Err_NONE ? "ok" : "ERR";
    }, py::arg("item"), py::arg("label"),
       py::call_guard<py::gil_scoped_release>());

    // ── Delete item from project ──
    m.def("delete_item", [](std::shared_ptr<Item> item) -> std::string {
        auto& msg = enqueueSyncTaskQuiet(DeleteItem, item->getItemHandle());
        msg->wait();
        return msg->getResult().error == A_Err_NONE ? "ok" : "ERR";
    }, py::arg("item"),
       py::call_guard<py::gil_scoped_release>());

    // ── Get item type ──
    m.def("get_item_type", [](std::shared_ptr<Item> item) -> int {
        auto& msg = enqueueSyncTaskQuiet(getItemType, item->getItemHandle());
        msg->wait();
        return static_cast<int>(msg->getResult().value);
    }, py::arg("item"),
       py::call_guard<py::gil_scoped_release>());

    // ── Get unique item ID ──
    m.def("get_item_id", [](std::shared_ptr<Item> item) -> int {
        auto& msg = enqueueSyncTaskQuiet(getUniqueItemID, item->getItemHandle());
        msg->wait();
        return static_cast<int>(msg->getResult().value);
    }, py::arg("item"),
       py::call_guard<py::gil_scoped_release>());

    // ══════════════════════════════════════════════════════════
    // ── Project Operations (native) ──
    // ══════════════════════════════════════════════════════════

    // ── Open project ──
    m.def("open_project", [](const std::string& path) -> std::string {
        auto& msg = enqueueSyncTaskQuiet(OpenProjectFromPath, path);
        msg->wait();
        auto result = msg->getResult();
        return result.error == A_Err_NONE ? "ok" : "ERR:" + std::to_string(result.error);
    }, py::arg("path"),
       py::call_guard<py::gil_scoped_release>());

    // ── New project ──
    m.def("new_project", []() -> std::string {
        auto& msg = enqueueSyncTaskQuiet(NewProject);
        msg->wait();
        return msg->getResult().error == A_Err_NONE ? "ok" : "ERR";
    }, py::call_guard<py::gil_scoped_release>());

    // ── Save project to path ──
    m.def("save_project", [](const std::string& path) -> std::string {
        auto& msg1 = enqueueSyncTaskQuiet(getProject);
        msg1->wait();
        auto projH = msg1->getResult();

        auto& msg2 = enqueueSyncTaskQuiet(SaveProjectToPath, projH, path);
        msg2->wait();
        return msg2->getResult().error == A_Err_NONE ? "ok" : "ERR";
    }, py::arg("path"),
       py::call_guard<py::gil_scoped_release>());

    // ── Is project dirty (unsaved changes) ──
    m.def("is_project_dirty", []() -> bool {
        auto& msg1 = enqueueSyncTaskQuiet(getProject);
        msg1->wait();
        auto& msg2 = enqueueSyncTaskQuiet(IsProjectDirty, msg1->getResult());
        msg2->wait();
        return msg2->getResult().value;
    }, py::call_guard<py::gil_scoped_release>());

    // ── Get/Set project bit depth ──
    m.def("get_project_bit_depth", []() -> std::string {
        auto& msg1 = enqueueSyncTaskQuiet(getProject);
        msg1->wait();
        auto& msg2 = enqueueSyncTaskQuiet(GetProjectBitDepth, msg1->getResult());
        msg2->wait();
        return msg2->getResult().value;
    }, py::call_guard<py::gil_scoped_release>());

    m.def("set_project_bit_depth", [](const std::string& depth) -> std::string {
        auto& msg1 = enqueueSyncTaskQuiet(getProject);
        msg1->wait();
        auto& msg2 = enqueueSyncTaskQuiet(SetProjectBitDepth, msg1->getResult(), depth);
        msg2->wait();
        return msg2->getResult().error == A_Err_NONE ? "ok" : "ERR";
    }, py::arg("depth"),
       py::call_guard<py::gil_scoped_release>());

    // ── Execute AE command by ID ──
    m.def("execute_command", [](int commandId) -> std::string {
        auto& msg = enqueueSyncTaskQuiet(ExecuteCommand, commandId);
        msg->wait();
        return msg->getResult().error == A_Err_NONE ? "ok" : "ERR";
    }, py::arg("command_id"),
       py::call_guard<py::gil_scoped_release>());
}

void bindManifest(py::module_& m)
{
    py::class_<Manifest>(m, "Manifest")
        .def(py::init<>())
        .def_readwrite("name", &Manifest::name)
        .def_readwrite("version", &Manifest::version)
        .def_readwrite("author", &Manifest::author)
        .def_readwrite("description", &Manifest::description)
        .def_readwrite("entry", &Manifest::entryPath)
        .def_readwrite("main", &Manifest::mainPath)
        .def_readwrite("use_js", &Manifest::useJS)
        .def_readwrite("dependencies", &Manifest::dependenciesFolder);
}

