// MessageQueue.h
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
#include <type_traits>
#include <utility>

/*
 * File: MessageQueue.h
 * Description: Manages asynchronous message processing within the After Effects plugin environment.
 *
 * Guidelines for Contributors:
 * 1. Understand the Flow: Grasp how messages are enqueued, processed, and dequeued.
 * 2. Thread Safety: Ensure that any modifications or additions respect the thread-safe nature of the queue.
 * 3. Interoperability: New messages or modifications should integrate seamlessly with existing asynchronous tasks.
 * 4. No Alteration: This file should not be changed. Understanding its functionality is key for effective contributions elsewhere.
 */


class IAsyncMessage {
public:
    virtual ~IAsyncMessage() = default;
    virtual void execute() = 0;
    virtual void wait() = 0;
    virtual void cancel() = 0;
    virtual bool isCancelled() const = 0;
};

namespace MessageQueueConfig {
    constexpr auto kWaitTimeout = std::chrono::seconds(5);
    constexpr std::size_t kMaxPendingMessages = 128;
}

template<typename T>
class AESyncMessage : public IAsyncMessage {
    std::function<T()> task;
    std::promise<T> finished;
    std::atomic<bool> cancelled{ false };

public:
    std::future<T> resultFuture;

    AESyncMessage(std::function<T()> taskFunc) : task(std::move(taskFunc)) {
        resultFuture = finished.get_future();
    }

    void execute() override {
        if (cancelled.load(std::memory_order_acquire) || !task) {
            return;
        }

        try {
            if constexpr (std::is_void_v<T>) {
                task();
                finished.set_value();
            } else {
                finished.set_value(task());
            }
        }
        catch (...) {
            try {
                finished.set_exception(std::current_exception());
            }
            catch (...) {
                // Promise may already be satisfied by timeout cancellation.
            }
        }
    }

    T getResult() {
        return resultFuture.get();
    }

    void wait() override {
        auto status = resultFuture.wait_for(MessageQueueConfig::kWaitTimeout);
        if (status == std::future_status::timeout) {
            cancel();
            throw std::runtime_error("AE IdleHook timeout (5s) - main thread not responding");
        }
    }

    void cancel() override {
        bool expected = false;
        if (cancelled.compare_exchange_strong(expected, true, std::memory_order_acq_rel)) {
            try {
                finished.set_exception(std::make_exception_ptr(
                    std::runtime_error("AE task cancelled after timeout")));
            }
            catch (...) {
                // Promise was already satisfied by execute().
            }
        }
    }

    bool isCancelled() const override {
        return cancelled.load(std::memory_order_acquire);
    }
};


class MessageQueue {
private:
    std::deque<std::shared_ptr<IAsyncMessage>> queue;
    std::mutex queueMutex;

    // Private constructor
    MessageQueue() {}

    // Deleted copy constructor and assignment operator
    MessageQueue(const MessageQueue&) = delete;
    MessageQueue& operator=(const MessageQueue&) = delete;

    void dropCancelledLocked() {
        queue.erase(
            std::remove_if(queue.begin(), queue.end(),
                [](const std::shared_ptr<IAsyncMessage>& message) {
                    return !message || message->isCancelled();
                }),
            queue.end());
    }

public:
    // Static method for accessing the singleton instance
    static MessageQueue& getInstance() {
        static MessageQueue instance;
        return instance;
    }

    void enqueue(std::shared_ptr<IAsyncMessage> message) {
        std::lock_guard<std::mutex> lock(queueMutex);
        dropCancelledLocked();
        if (queue.size() >= MessageQueueConfig::kMaxPendingMessages) {
            throw std::runtime_error("AE task queue overloaded - main thread is not draining tasks");
        }
        queue.push_back(message);
    }

    std::shared_ptr<IAsyncMessage> dequeue() {
        std::lock_guard<std::mutex> lock(queueMutex);
        dropCancelledLocked();
        if (!queue.empty()) {
            auto message = queue.front();
            queue.pop_front();
            return message;
        }
        return nullptr;
    }

    bool hasPending() {
        std::lock_guard<std::mutex> lock(queueMutex);
        dropCancelledLocked();
        return !queue.empty();
    }

    std::size_t size() {
        std::lock_guard<std::mutex> lock(queueMutex);
        dropCancelledLocked();
        return queue.size();
    }
};
