// TaskUtilsQuiet.h
// Drop-in replacement for enqueueSyncTask that does NOT call CauseIdleRoutinesToBeCalled.
// Instead uses PostMessage(WM_NULL) to safely wake AE's message pump from any thread.
#pragma once
#include "MessageQueue.h"

#ifdef AE_OS_WIN
#include <windows.h>
#endif

#include <tuple>

template<typename Func, typename... Args>
auto enqueueSyncTaskQuiet(Func&& func, Args&&... args) {
    using ReturnType = std::invoke_result_t<Func, Args...>;

    auto task = [func = std::forward<Func>(func), argsTuple = std::make_tuple(std::forward<Args>(args)...)]() mutable -> ReturnType {
        return std::apply(func, argsTuple);
    };

    auto message = std::make_shared<AESyncMessage<ReturnType>>(std::move(task));

    MessageQueue::getInstance().enqueue(message);

    // Wake AE's message pump via PostMessage (thread-safe, no main-thread requirement)
    // EnumWindows to find AE_CApplication_* regardless of version
#ifdef AE_OS_WIN
    struct FindAE {
        HWND result = NULL;
        static BOOL CALLBACK cb(HWND hwnd, LPARAM lp) {
            wchar_t cls[64] = {};
            GetClassNameW(hwnd, cls, 64);
            if (wcsstr(cls, L"AE_CApplication") != NULL) {
                reinterpret_cast<FindAE*>(lp)->result = hwnd;
                return FALSE; // stop
            }
            return TRUE;
        }
    } finder;
    EnumWindows(FindAE::cb, reinterpret_cast<LPARAM>(&finder));
    if (finder.result) PostMessageW(finder.result, WM_NULL, 0, 0);
#endif

    return message;
}
