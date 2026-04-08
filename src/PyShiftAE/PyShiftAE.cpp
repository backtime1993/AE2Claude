
/*	
	PyShiftAE.cpp

	Main Implementation file for PyShiftAE


	version		notes							engineer				date
	
	1.0			First implementation			Trentonom0r3 (Spigon) 	10/31/2023
	
*/
#include "PyShiftAE.h"
#include <filesystem>
#include <fstream>
#include "CoreLib/Json.h"
#include "MessageManager.h"

// ---- DllMain debug: catch load-time crashes ----
#ifdef AE_OS_WIN
BOOL APIENTRY DllMain(HMODULE hModule, DWORD reason, LPVOID lpReserved)
{
	if (reason == DLL_PROCESS_ATTACH) {
		// Write a marker file as early as possible
		wchar_t tempDir[MAX_PATH];
		GetTempPathW(MAX_PATH, tempDir);
		std::wstring markerPath = std::wstring(tempDir) + L"AE2Claude\\dllmain_attach.txt";
		CreateDirectoryW((std::wstring(tempDir) + L"AE2Claude").c_str(), NULL);
		HANDLE hFile = CreateFileW(
			markerPath.c_str(),
			GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
		if (hFile != INVALID_HANDLE_VALUE) {
			const char msg[] = "DllMain DLL_PROCESS_ATTACH reached\r\n";
			DWORD written;
			WriteFile(hFile, msg, sizeof(msg) - 1, &written, NULL);
			CloseHandle(hFile);
		}
	}
	return TRUE;
}
#endif

static AEGP_PluginID		PyShiftAE			=	6969L;
static AEGP_Command			PyShift				=	6769L;
static A_long				S_idle_count		=	0L;
static SPBasicSuite			*sP					=	NULL;
static AEGP_Command			console			    =   7991L;


PanelatorUI_Plat* PanelatorUI_Plat::instance = nullptr;

std::queue<ScriptTask> scriptExecutionQueue;
std::mutex scriptQueueMutex; // To ensure thread safety
std::atomic<bool> pythonThreadRunning = true;
std::atomic<bool> shouldExitPythonThread = false;

std::mutex resultsMutex;
std::thread pythonThread;
std::condition_variable scriptAddedCond;

bool newScriptAdded = false;

namespace {

std::filesystem::path GetPluginModulePath()
{
#ifdef AE_OS_WIN
	HMODULE moduleHandle = nullptr;
	if (!GetModuleHandleExW(
		GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
		reinterpret_cast<LPCWSTR>(&EntryPointFunc),
		&moduleHandle)) {
		return {};
	}

	std::wstring buffer(MAX_PATH, L'\0');
	for (;;) {
		DWORD copied = GetModuleFileNameW(moduleHandle, buffer.data(), static_cast<DWORD>(buffer.size()));
		if (copied == 0) {
			return {};
		}
		if (copied < buffer.size() - 1) {
			buffer.resize(copied);
			return std::filesystem::path(buffer);
		}
		buffer.resize(buffer.size() * 2);
	}
#else
	return {};
#endif
}

std::filesystem::path GetLogDirectory()
{
	std::error_code ec;
	auto logDir = std::filesystem::temp_directory_path(ec);
	if (ec || logDir.empty()) {
		logDir = std::filesystem::current_path(ec);
	}
	logDir /= "AE2Claude";
	std::filesystem::create_directories(logDir, ec);
	return logDir;
}

void WriteTextFile(const std::filesystem::path& path, const std::string& content)
{
	std::error_code ec;
	if (!path.parent_path().empty()) {
		std::filesystem::create_directories(path.parent_path(), ec);
	}
	std::ofstream stream(path, std::ios::binary | std::ios::trunc);
	if (stream) {
		stream << content;
	}
}

void AppendTextFile(const std::filesystem::path& path, const std::string& content)
{
	std::error_code ec;
	if (!path.parent_path().empty()) {
		std::filesystem::create_directories(path.parent_path(), ec);
	}
	std::ofstream stream(path, std::ios::binary | std::ios::app);
	if (stream) {
		stream << content;
	}
}

std::filesystem::path ResolveServerScriptPath()
{
	std::error_code ec;
	const auto modulePath = GetPluginModulePath();
	if (modulePath.empty()) {
		return {};
	}

	const auto moduleDir = modulePath.parent_path();
	const auto direct = moduleDir / "ae2claude_server.py";
	if (std::filesystem::exists(direct, ec)) {
		return direct;
	}

	const auto buildFallback = moduleDir.parent_path().parent_path().parent_path() / "ae2claude_server.py";
	if (std::filesystem::exists(buildFallback, ec)) {
		return buildFallback;
	}

	return {};
}

} // namespace


static A_Err
S_CreatePanelHook(
	AEGP_GlobalRefcon		plugin_refconP,
	AEGP_CreatePanelRefcon	refconP,
	AEGP_PlatformViewRef	container, //HWN
	AEGP_PanelH				panelH,
	AEGP_PanelFunctions1* outFunctionTable,
	AEGP_PanelRefcon* outRefcon)
{
	try {
		Manifest* manifest = reinterpret_cast<Manifest*>(refconP);
		std::string name = manifest->name;
		std::string version = manifest->version;
		std::string sessionID = name + version;
		// Construct the path to the Python executable in the venv
		std::filesystem::path entryPathObj(manifest->entryPath);
		std::filesystem::path venvPath = entryPathObj.parent_path() / "venv" / "Scripts" / "python.exe";
		// Form the command to run the Python script
		std::string venvPathS = venvPath.string();
		//create command which is the path to the python executable, followed by the path to the script, wrapped in quotes
		std::string command = "\"" + venvPathS + "\" \"" + manifest->entryPath + "\"";

		std::cout << "Executing command: " << command << std::endl;
		SessionManager::GetInstance().executeCommandAsync(command, sessionID);

		int timeout = 100;
		while (timeout > 0) {
			if (SessionManager::GetInstance().isHWNDStored(sessionID)) {
				break;
			}
			std::this_thread::sleep_for(std::chrono::milliseconds(100));
			timeout--;
			if (timeout == 0) {
				std::cout << "Timeout reached" << std::endl;
				App app;
				app.reportInfo("Timed out finding HWND");
				return A_Err_PARAMETER;
			}
		}

		PanelatorUI_Plat* myPanel = new PanelatorUI_Plat(sessionID, sP, panelH, container, outFunctionTable);
		*outRefcon = reinterpret_cast<AEGP_PanelRefcon>(myPanel);
		return A_Err_NONE;
	}
	catch (std::exception& e) {
		std::cout << e.what() << std::endl;
		std::string error = e.what();
	}
	catch (std::filesystem::filesystem_error& e) {
		std::cout << e.what() << std::endl;
		std::string error = e.what();
	}
	catch (...) {
		std::cout << "Unknown error occurred" << std::endl;
	}
}


std::vector<Manifest> getManifests() {
	// CEP extensions removed in AE 2025+. Skip scanning.
	return std::vector<Manifest>();
}

void ensurePythonHome() {
	// Embedded Python needs PYTHONHOME to find the standard library (encodings, etc.)
	// Only set if not already defined by the environment.
	static std::wstring pythonHome;
	if (pythonHome.empty() && !std::getenv("PYTHONHOME")) {
		// Locate python312.dll next to AfterFX.exe, then resolve the real Python prefix
		// via the registry or a known scoop install path.
		const wchar_t* candidates[] = {
			L"C:\\Python312",
			L"C:\\Program Files\\Python312",
		};
		for (auto* c : candidates) {
			auto lib = std::filesystem::path(c) / "Lib" / "encodings" / "__init__.py";
			if (std::filesystem::exists(lib)) {
				pythonHome = c;
				Py_SetPythonHome(pythonHome.c_str());
				return;
			}
		}
	}
}

void startPythonThread(std::atomic<bool>& shouldExitPythonThread, std::mutex& scriptQueueMutex, std::condition_variable& scriptAddedCond, std::queue<ScriptTask>& scriptExecutionQueue) {
	// Assign to the GLOBAL pythonThread (not a local shadow) so DeathHook can join it
	pythonThread = std::thread([&]() {
		try {
			ensurePythonHome();
			py::scoped_interpreter guard{}; // start the interpreter and keep it alive
			const auto logDir = GetLogDirectory();
			const auto aliveLogPath = (logDir / "ae2claude_alive.txt").string();
			const auto cppErrorLogPath = logDir / "ae2claude_cpp_error.txt";

			// DEBUG: Write file to check if Python interpreter is alive
			try {
				py::globals()["__pyshiftae_alive_path"] = aliveLogPath;
				py::exec(R"PY(
with open(__pyshiftae_alive_path, 'w', encoding='utf-8') as f:
    f.write('Python interpreter alive!\n')
    import sys
    f.write('Python: ' + sys.version + '\n')
    try:
        import PyShiftCore
        f.write('PyShiftCore imported OK\n')
    except Exception as ex:
        f.write('PyShiftCore import failed: ' + str(ex) + '\n')
    try:
        from http.server import HTTPServer, BaseHTTPRequestHandler
        import threading
        f.write('http.server imported OK\n')
    except Exception as ex:
        f.write('http.server import failed: ' + str(ex) + '\n')
)PY");
			}
			catch (const std::exception& e) {
				WriteTextFile(cppErrorLogPath, std::string("C++ exception: ") + e.what() + "\n");
			}
			catch (...) {
				WriteTextFile(cppErrorLogPath, "Unknown C++ exception\n");
			}

			// Auto-start HTTP server for external communication
			try {
				const auto serverScript = ResolveServerScriptPath();
				if (!serverScript.empty()) {
					py::module_ sys = py::module_::import("sys");
					sys.attr("path").attr("insert")(0, serverScript.parent_path().string());
					py::module_::import("runpy").attr("run_path")(serverScript.string());
				}
				else {
					AppendTextFile(cppErrorLogPath, "Server script not found next to plugin or build output.\n");
				}
			}
			catch (const std::exception& e) {
				std::cerr << "AE2Claude server error: " << e.what() << std::endl;
				AppendTextFile(cppErrorLogPath, std::string("AE2Claude server error: ") + e.what() + "\n");
			}
			catch (...) {
				std::cerr << "AE2Claude server unknown error" << std::endl;
				AppendTextFile(cppErrorLogPath, "AE2Claude server unknown error\n");
			}

			while (!shouldExitPythonThread.load()) {
				ScriptTask task;

				{
					// Release GIL while waiting so HTTP/pipe server threads can run
					py::gil_scoped_release release;
					std::unique_lock<std::mutex> lock(scriptQueueMutex);
					scriptAddedCond.wait(lock, [&] { return !scriptExecutionQueue.empty() || shouldExitPythonThread.load(); });

					if (shouldExitPythonThread.load()) break;

					if (!scriptExecutionQueue.empty()) {
						task = std::move(scriptExecutionQueue.front());
						scriptExecutionQueue.pop();
					}
				}

				if (!task.scriptPath.empty()) {
					switch (task.resultType) {
					case ScriptTask::ManifestType:
						task.manifestPromise.set_value(executeManifestFromFile(task.scriptPath));
						break;
					case ScriptTask::NoResult:
						executeFromFile(task.scriptPath);
						break;
					case ScriptTask::GUIType:
						break;
					}
				}
			}
	}
	catch (const std::exception& e) {
		std::cerr << "AE2Claude Python thread error: " << e.what() << std::endl;
		AppendTextFile(GetLogDirectory() / "ae2claude_cpp_error.txt", std::string("AE2Claude Python thread error: ") + e.what() + "\n");
	}
	catch (...) {
		std::cerr << "AE2Claude Python thread unknown error" << std::endl;
		AppendTextFile(GetLogDirectory() / "ae2claude_cpp_error.txt", "AE2Claude Python thread unknown error\n");
	}
	});
	// Do NOT detach — DeathHook will join this thread for clean shutdown
}

static A_Err
DeathHook(
	AEGP_GlobalRefcon	plugin_refconP,
	AEGP_DeathRefcon	refconP)
{
	A_Err	err			= A_Err_NONE;

	// Signal the Python thread to exit
	pythonThreadRunning = false;
	shouldExitPythonThread = true;
	scriptAddedCond.notify_all();  // Wake up the thread if it's waiting

	if (pythonThread.joinable()) {
		pythonThread.join();
	}

	SessionManager::GetInstance().cleanAll();
	return err;
}

static A_Err
UpdateMenuHook(
	AEGP_GlobalRefcon		plugin_refconPV,	/* >> */
	AEGP_UpdateMenuRefcon	refconPV,			/* >> */
	AEGP_WindowType			active_window)		/* >> */
{
	A_Err 				err = A_Err_NONE,
		err2 = A_Err_NONE;


	AEGP_SuiteHandler	suites(sP);
	SuiteHelper<AEGP_PanelSuite1>	i_ps(sP);
	A_Boolean	out_thumb_is_shownB = FALSE, out_panel_is_frontmostB = FALSE;

	Manifests *manifests = reinterpret_cast<Manifests*>(plugin_refconPV);
	for (int i = 0; i < manifests->manifests.size(); i++) {
		if (manifests->manifests[i].useJS == FALSE)
		{
			ERR(suites.CommandSuite1()->AEGP_EnableCommand(manifests->manifests[i].command));
			i_ps->AEGP_IsShown(reinterpret_cast<const A_u_char*>(manifests->manifests[i].name.c_str()), &out_thumb_is_shownB, &out_panel_is_frontmostB);
			suites.CommandSuite1()->AEGP_CheckMarkMenuCommand(manifests->manifests[i].command, out_thumb_is_shownB && out_panel_is_frontmostB);
		}
	}
	ERR(suites.CommandSuite1()->AEGP_EnableCommand(PyShift));
	return err;
}


static A_Err IdleHook(AEGP_GlobalRefcon plugin_refconP, AEGP_IdleRefcon refconP, A_long* max_sleepPL) {
	A_Err err = A_Err_NONE;

	// Process all pending messages (not just one)
	auto message = MessageQueue::getInstance().dequeue();
	while (message != nullptr) {
		message->execute();
		message = MessageQueue::getInstance().dequeue();
	}

	// Request fast idle callback (10ms) so HTTP thread waits are short
	if (max_sleepPL) {
		*max_sleepPL = 10;  // milliseconds
	}

	return err;
}

static A_Err
CommandHook(
	AEGP_GlobalRefcon    plugin_refconPV,        /* >> */
	AEGP_CommandRefcon    refconPV,                /* >> */
	AEGP_Command        command,                /* >> */
	AEGP_HookPriority    hook_priority,            /* >> */
	A_Boolean            already_handledB,        /* >> */
	A_Boolean* handledPB)                /* << */
{
	A_Err            err = A_Err_NONE,
		err2 = A_Err_NONE;

	AEGP_SuiteHandler    suites(sP);
	SuiteHelper<AEGP_PanelSuite1>	i_ps(sP);

	if (command == PyShift) {
		std::cout << "PyShift Command Received" << std::endl;

		// Get the main window handle of After Effects
		HWND ae_hwnd;
		suites.UtilitySuite6()->AEGP_GetMainHWND(&ae_hwnd);

		// Set up an OPENFILENAME structure to configure the file picker dialog
		OPENFILENAME ofn;
		ZeroMemory(&ofn, sizeof(OPENFILENAME));
		ofn.lStructSize = sizeof(OPENFILENAME);
		ofn.hwndOwner = ae_hwnd;
		ofn.lpstrFilter = "Python Scripts (*.py)\0*.py\0All Files (*.*)\0*.*\0";
		ofn.lpstrFile = new CHAR[MAX_PATH];
		ofn.lpstrFile[0] = '\0';
		ofn.nMaxFile = MAX_PATH;
		ofn.Flags = OFN_EXPLORER | OFN_FILEMUSTEXIST | OFN_HIDEREADONLY;
		ofn.lpstrDefExt = "py";

		// Show the file picker dialog
		if (GetOpenFileName(&ofn)) {
			std::string scriptPath = ofn.lpstrFile;
			ScriptTask task;
			task.scriptPath = scriptPath;
			task.resultType = ScriptTask::NoResult;
			{
				std::lock_guard<std::mutex> lock(scriptQueueMutex);
				scriptExecutionQueue.push(std::move(task));
				scriptAddedCond.notify_one();

			}
		}

		else {
			// User cancelled the dialog or an error occurred
			DWORD error = CommDlgExtendedError();
			if (error) {
				std::cerr << "File dialog error: " << error << std::endl;
			}
			else {
				std::cerr << "No script file selected" << std::endl;
			}
		}

		delete[] ofn.lpstrFile;

		*handledPB = TRUE;  // Mark the command as handled
	}
	else {
 		Manifests* manifests = reinterpret_cast<Manifests*>(plugin_refconPV);
		for (int i = 0; i < manifests->manifests.size(); i++) {
			if (command == manifests->manifests[i].command) {
				//run the manifest
				//get the manifest from the vector
				Manifest manifest = manifests->manifests[i];
				std::string name = manifest.name;

			    //show the panel that matches the manifest name
				i_ps->AEGP_ToggleVisibility(reinterpret_cast<const A_u_char*>(name.c_str()));

			}
			*handledPB = TRUE;
			return err;
		}
		*handledPB = FALSE;
	}

	return err;
}

A_Err
EntryPointFunc(
	struct SPBasicSuite* pica_basicP,		/* >> */
	A_long				 	major_versionL,		/* >> */
	A_long					minor_versionL,		/* >> */
	AEGP_PluginID			aegp_plugin_id,		/* >> */
	AEGP_GlobalRefcon* global_refconV)	/* << */
{	

	PyShiftAE = aegp_plugin_id;

	// DEBUG: Verify plugin is loading
	{
		WriteTextFile(
			GetLogDirectory() / "ae2claude_entry.txt",
			"EntryPointFunc called! Plugin ID: " + std::to_string(aegp_plugin_id) + "\n");
	}

	A_Err 					err = A_Err_NONE,
							err2 = A_Err_NONE;

	sP = pica_basicP;

	// Initialize the suite managers
	SuiteManager::GetInstance().InitializeSuiteHandler(sP);
	AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
	SuiteManager::GetInstance().InitializePanelSuiteHandler(sP);

	SuiteManager::GetInstance().SetPluginID(&PyShiftAE); // Set the plugin ID

	shouldExitPythonThread = false;
	pythonThreadRunning = true;
	startPythonThread(shouldExitPythonThread, scriptQueueMutex, scriptAddedCond, scriptExecutionQueue);
	
	ERR(suites.CommandSuite1()->AEGP_GetUniqueCommand(&PyShift));

	ERR(suites.CommandSuite1()->AEGP_InsertMenuCommand(PyShift,
		"Run Script (.py)",
		AEGP_Menu_FILE,
		AEGP_MENU_INSERT_SORTED));

	ERR(suites.RegisterSuite5()->AEGP_RegisterCommandHook(PyShiftAE,
		AEGP_HP_BeforeAE,
		AEGP_Command_ALL,
		CommandHook,
		0));

	ERR(suites.RegisterSuite5()->AEGP_RegisterDeathHook(PyShiftAE, DeathHook, NULL));

	ERR(suites.RegisterSuite5()->AEGP_RegisterUpdateMenuHook(PyShiftAE, UpdateMenuHook, NULL));

	ERR(suites.RegisterSuite5()->AEGP_RegisterIdleHook(PyShiftAE, IdleHook, NULL));

	if (err) { // not !err, err!
		ERR2(suites.UtilitySuite3()->AEGP_ReportInfo(PyShiftAE, "AE2Claude : Could not register command hook."));
	}
	
	std::vector<Manifest> manifests = getManifests();
	Manifests *manifestsP = new Manifests();
	manifestsP->manifests = manifests;
	*global_refconV = reinterpret_cast<AEGP_GlobalRefcon>(manifestsP);
	SessionManager::GetInstance();

	return err;
}
		
