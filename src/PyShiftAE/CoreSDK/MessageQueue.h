#pragma once
#include <algorithm>
#include <atomic>
#include <chrono>
#include <deque>
#include <exception>
#include <functional>
#include <future>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <thread>
#include <type_traits>
#include <utility>

namespace MessageQueueConfig {
    constexpr auto kWaitTimeout = std::chrono::seconds(120);
    constexpr std::size_t kMaxPendingMessages = 128;
    constexpr auto kIdleBudget = std::chrono::milliseconds(4);
    constexpr std::size_t kMaxMessagesPerIdle = 32;
    // AEGP_IdleHook uses 1/60-second ticks, NOT milliseconds.
    constexpr long kPendingSleepTicks = 1;
    constexpr long kEmptySleepTicks = 15;
}

struct QueueMetrics {
    std::atomic<unsigned long long> submitted{0}, completed{0}, cancelled{0}, rejected{0};
    std::atomic<unsigned long long> lastWaitUs{0}, lastExecutionUs{0}, overruns{0};
    std::atomic<unsigned long long> idleCalls{0}, lastIdleNs{0};
    std::atomic<unsigned int> running{0};
    static QueueMetrics& get() { static QueueMetrics metrics; return metrics; }
    static unsigned long long nowNs() {
        return static_cast<unsigned long long>(std::chrono::duration_cast<std::chrono::nanoseconds>(
            std::chrono::steady_clock::now().time_since_epoch()).count());
    }
};

class IAsyncMessage {
public:
    virtual ~IAsyncMessage() = default;
    virtual void execute() = 0;
    virtual void wait() = 0;
    virtual void cancel() = 0;
    virtual bool isCancelled() const = 0;
};

template<typename T>
class AESyncMessage : public IAsyncMessage {
    enum class State { Pending, Running, Completed, Cancelled };
    std::function<T()> task;
    std::promise<T> finished;
    std::atomic<State> state{State::Pending};
    const unsigned long long enqueuedNs = QueueMetrics::nowNs();
public:
    std::future<T> resultFuture;
    explicit AESyncMessage(std::function<T()> taskFunc) : task(std::move(taskFunc)), resultFuture(finished.get_future()) {}
    void execute() override {
        State expected = State::Pending;
        if (!state.compare_exchange_strong(expected, State::Running)) return;
        auto& metrics = QueueMetrics::get();
        const auto start = QueueMetrics::nowNs();
        metrics.lastWaitUs = (start - enqueuedNs) / 1000;
        ++metrics.running;
        try {
            if constexpr (std::is_void_v<T>) { task(); finished.set_value(); }
            else { finished.set_value(task()); }
        } catch (...) {
            finished.set_exception(std::current_exception());
        }
        metrics.lastExecutionUs = (QueueMetrics::nowNs() - start) / 1000;
        --metrics.running;
        ++metrics.completed;
        state.store(State::Completed);
    }
    T getResult() { return resultFuture.get(); }
    void wait() override { waitFor(MessageQueueConfig::kWaitTimeout); }
    void waitFor(std::chrono::milliseconds timeout) {
        if (resultFuture.wait_for(timeout) != std::future_status::timeout) return;
        cancel();
        if (isCancelled()) throw std::runtime_error("AE task deadline expired before execution; outcome=not_started");
        // Running SDK calls cannot be interrupted safely. Some wrappers capture
        // caller-owned references, so keep the caller alive until completion.
        // The independent HTTP deadline still reports outcome=unknown to clients.
        ++QueueMetrics::get().overruns;
        resultFuture.wait();
    }
    void cancel() override {
        State expected = State::Pending;
        if (state.compare_exchange_strong(expected, State::Cancelled)) {
            ++QueueMetrics::get().cancelled;
            finished.set_exception(std::make_exception_ptr(
                std::runtime_error("AE task cancelled before execution; outcome=not_started")));
        }
    }
    bool isCancelled() const override { return state.load() == State::Cancelled; }
};

class MessageQueue {
    std::deque<std::shared_ptr<IAsyncMessage>> queue;
    std::mutex queueMutex;
    std::function<void()> wake;
    std::thread::id mainThread;
    bool stopped = false;
    MessageQueue() = default;
    MessageQueue(const MessageQueue&) = delete;
    MessageQueue& operator=(const MessageQueue&) = delete;
    void dropCancelledLocked() {
        queue.erase(std::remove_if(queue.begin(), queue.end(), [](const auto& m) {
            return !m || m->isCancelled();
        }), queue.end());
    }
public:
    static MessageQueue& getInstance() { static MessageQueue instance; return instance; }
    // Initialize on AE's main thread before any producer is started.
    void initialize(std::function<void()> callback) {
        std::lock_guard<std::mutex> lock(queueMutex);
        mainThread = std::this_thread::get_id();
        wake = std::move(callback);
        stopped = false;
    }
    void enqueue(std::shared_ptr<IAsyncMessage> message) {
        if (!message) throw std::invalid_argument("Null AE task");
        std::function<void()> notify;
        bool inlineExecution;
        {
            std::lock_guard<std::mutex> lock(queueMutex);
            if (stopped) { ++QueueMetrics::get().rejected; throw std::runtime_error("AE dispatcher is shutting down; outcome=not_started"); }
            inlineExecution = mainThread == std::this_thread::get_id();
            if (!inlineExecution) {
                dropCancelledLocked();
                if (queue.size() >= MessageQueueConfig::kMaxPendingMessages) {
                    ++QueueMetrics::get().rejected;
                    throw std::runtime_error("AE task queue overloaded; outcome=not_started");
                }
                const bool wasEmpty = queue.empty();
                queue.push_back(message);
                if (wasEmpty) notify = wake;
            }
            ++QueueMetrics::get().submitted;
        }
        if (inlineExecution) message->execute();
        else if (notify) notify();
    }
    std::shared_ptr<IAsyncMessage> dequeue() {
        std::lock_guard<std::mutex> lock(queueMutex);
        dropCancelledLocked();
        if (queue.empty()) return nullptr;
        auto message = queue.front(); queue.pop_front(); return message;
    }
    std::size_t size() {
        std::lock_guard<std::mutex> lock(queueMutex);
        dropCancelledLocked(); return queue.size();
    }
    bool hasPending() { return size() != 0; }
    std::size_t drain(std::chrono::milliseconds budget = MessageQueueConfig::kIdleBudget,
                      std::size_t maximum = MessageQueueConfig::kMaxMessagesPerIdle) {
        ++QueueMetrics::get().idleCalls;
        QueueMetrics::get().lastIdleNs = QueueMetrics::nowNs();
        auto started = std::chrono::steady_clock::now();
        std::size_t processed = 0;
        while (processed < maximum) {
            auto message = dequeue();
            if (!message) break;
            message->execute();
            ++processed;
            if (std::chrono::steady_clock::now() - started >= budget) break;
        }
        return processed;
    }
    void shutdown() {
        std::lock_guard<std::mutex> lock(queueMutex);
        stopped = true;
        for (auto& message : queue) if (message) message->cancel();
        queue.clear();
    }
};
