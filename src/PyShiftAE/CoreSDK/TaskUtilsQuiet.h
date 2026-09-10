#pragma once
#include "TaskUtils.h"

// Source compatibility: both routes now use the cached SDK wake pointer.
template<typename Func, typename... Args>
auto enqueueSyncTaskQuiet(Func&& func, Args&&... args) {
    return enqueueSyncTask(std::forward<Func>(func), std::forward<Args>(args)...);
}
