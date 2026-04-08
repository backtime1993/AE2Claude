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
    // WM_NULL is a no-op message that just pokes the event loop
#ifdef AE_OS_WIN
    HWND aeWnd = FindWindowW(L"AE_CApplication_26.1", NULL);
    if (!aeWnd) aeWnd = FindWindowW(L"AE_CApplication_25.0", NULL);
    if (!aeWnd) aeWnd = FindWindowW(NULL, NULL);  // fallback
    if (aeWnd) PostMessageW(aeWnd, WM_NULL, 0, 0);
#endif

    return message;
}
