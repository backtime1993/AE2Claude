// Include the header file for linking with Python.
#include "PyLink.h"
#include "../CoreSDK/NativeAutomation.h"
#include "../CoreSDK/NativeAutomationValidation.h"

using namespace pybind11::literals;

PYBIND11_EMBEDDED_MODULE(PyShiftCore, m) {
    m.def("bridgeDiagnostics", []() {
        const auto& metrics = QueueMetrics::get();
        py::dict result;
        result["revision"] = "dispatcher-20260910";
        result["automationRevision"] = NativeAutomation::kRevision;
        result["pending"] = MessageQueue::getInstance().size();
        result["running"] = metrics.running.load();
        result["submitted"] = metrics.submitted.load();
        result["completed"] = metrics.completed.load();
        result["cancelledBeforeStart"] = metrics.cancelled.load();
        result["rejected"] = metrics.rejected.load();
        result["lastQueueWaitUs"] = metrics.lastWaitUs.load();
        result["lastExecutionUs"] = metrics.lastExecutionUs.load();
        result["runningDeadlineOverruns"] = metrics.overruns.load();
        result["idleCalls"] = metrics.idleCalls.load();
        const auto lastIdle = metrics.lastIdleNs.load();
        result["lastIdleAgoMs"] = lastIdle ? (QueueMetrics::nowNs() - lastIdle) / 1000000 : 0;
        result["idleSeen"] = lastIdle != 0;
        result["idleBudgetMs"] = MessageQueueConfig::kIdleBudget.count();
        result["maxPending"] = MessageQueueConfig::kMaxPendingMessages;
        result["pendingSleepTicks"] = MessageQueueConfig::kPendingSleepTicks;
        result["emptySleepTicks"] = MessageQueueConfig::kEmptySleepTicks;
        result["wakeMode"] = "cached-sdk-callback";
        result["forcedInterruption"] = false;
        return result;
    });
    bindLayer(m);
    bindItem(m);
    bindCompItem(m);
    bindFootageItem(m);
    bindFolderItem(m);
    bindProject(m);
    bindApp(m);
    //bind the LayerFlag enum
    bindLayerEnum(m);
    bindLayerCollection(m);
    bindProjectCollection(m);
    bindItemCollection(m);
    bindAdjustmentLayerItem(m);
    bindSolidItem(m);
    bindManifest(m);
    bindStreamUtils(m);
    bindNativeAutomation(m);

}

void createVenv(const std::string& scriptPath) {
    try {
		py::module psc = py::module::import("PyShiftAE");
		py::function createVenv = psc.attr("create_venv");
        createVenv(scriptPath);
	}
    catch (const py::error_already_set& e) {
		// Handle any exceptions thrown by pybind11.
		std::cerr << "Python exception: " << e.what() << std::endl;
	}
    catch (const py::reference_cast_error& e) {
		std::cerr << "Cast error: " << e.what() << std::endl;
	}
    catch (const py::cast_error& e) {
        std::cerr << "Cast error: " << e.what() << std::endl;
    }
    catch (const std::exception& e) {
		// Handle any standard C++ exceptions.
		std::cerr << "Standard exception: " << e.what() << std::endl;
	}
    catch (...) {
		// Catch all other exceptions.
		std::cerr << "Unknown exception occurred" << std::endl;
	}
}

Manifest executeManifestFromFile(const std::string& scriptPath) {
	Manifest manifest;
    try {
        //py::scoped_interpreter guard{}; // start the interpreter and keep it alive
        py::gil_scoped_acquire acquire;
        py::globals().clear();
        //py::object pyShiftCore = py::module_::import("PyShiftCore");
        //clear globals
        py::object result = py::eval_file(scriptPath);
        manifest = py::globals()["manifest"].cast<Manifest>();
        createVenv(scriptPath);
	}
    catch (const py::error_already_set& e) {
		// Handle any exceptions thrown by pybind11.
		std::cerr << "Python exception: " << e.what() << std::endl;
		manifest = Manifest();
	}
    catch (const py::reference_cast_error& e) {
        std::cerr << "Cast error: " << e.what() << std::endl;
        manifest = Manifest();
    }
    catch (const py::cast_error& e) {
		std::cerr << "Cast error: " << e.what() << std::endl;
		manifest = Manifest();
	}
    catch (...) {
		// Catch all other exceptions.
		std::cerr << "Unknown exception occurred" << std::endl;
		manifest = Manifest();
	}
	return manifest;
}

void executeFromFile(const std::string& scriptPath) {
    try {
        py::gil_scoped_acquire acquire;
        //py::object pyShiftCore = py::module_::import("PyShiftCore");

        py::eval_file(scriptPath);
    }
    catch (const py::error_already_set& e) {
		// Handle any exceptions thrown by pybind11.
		std::cerr << "Python exception: " << e.what() << std::endl;
	}
    catch (const std::exception& e) {
		// Handle any standard C++ exceptions.
		std::cerr << "Standard exception: " << e.what() << std::endl;
	}
    catch (...) {
		// Catch all other exceptions.
		std::cerr << "Unknown exception occurred" << std::endl;
	}
}
