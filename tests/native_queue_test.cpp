#include "../src/PyShiftAE/CoreSDK/MessageQueue.h"
#include "../src/PyShiftAE/CoreSDK/ScriptJson.h"
#include <cassert>
#include <iostream>
#include <vector>

int main() {
    using namespace std::chrono_literals;
    auto& queue = MessageQueue::getInstance();
    std::atomic<int> wakes{0}, calls{0};
    queue.initialize([&] { ++wakes; });
    auto inlineTask = std::make_shared<AESyncMessage<int>>([] { return 42; });
    queue.enqueue(inlineTask);
    inlineTask->wait();
    assert(inlineTask->getResult() == 42 && queue.size() == 0 && wakes == 0);

    std::shared_ptr<AESyncMessage<int>> expired;
    std::thread expire([&] {
        expired = std::make_shared<AESyncMessage<int>>([&] { ++calls; return 1; });
        queue.enqueue(expired);
        bool caught = false;
        try { expired->waitFor(1ms); } catch (const std::runtime_error&) { caught = true; }
        assert(caught);
    });
    expire.join(); queue.drain();
    assert(expired->isCancelled() && calls == 0 && queue.size() == 0);

    std::atomic<bool> started{false};
    auto running = std::make_shared<AESyncMessage<int>>([&] { started = true; std::this_thread::sleep_for(30ms); return 7; });
    std::thread runner([&] { running->execute(); });
    while (!started) std::this_thread::yield();
    auto waitStart = std::chrono::steady_clock::now();
    running->waitFor(1ms);
    assert(std::chrono::steady_clock::now() - waitStart >= 20ms);
    assert(running->getResult() == 7 && !running->isCancelled());
    runner.join();

    std::vector<std::shared_ptr<AESyncMessage<int>>> slice;
    std::thread producer([&] {
        for (int i = 0; i < 8; ++i) {
            auto task = std::make_shared<AESyncMessage<int>>([] { std::this_thread::sleep_for(3ms); return 1; });
            slice.push_back(task); queue.enqueue(task);
        }
    });
    producer.join();
    auto processed = queue.drain(4ms, 32);
    assert(processed >= 1 && processed <= 2 && queue.size() >= 6);
    queue.shutdown();
    for (std::size_t i = processed; i < slice.size(); ++i) assert(slice[i]->isCancelled());
    bool rejected = false;
    try { queue.enqueue(std::make_shared<AESyncMessage<int>>([] { return 1; })); }
    catch (const std::runtime_error&) { rejected = true; }
    assert(rejected);
    queue.initialize([&] { ++wakes; });

    std::thread overload([&] {
        for (std::size_t i = 0; i < MessageQueueConfig::kMaxPendingMessages; ++i)
            queue.enqueue(std::make_shared<AESyncMessage<int>>([] { return 1; }));
        bool caught = false;
        try { queue.enqueue(std::make_shared<AESyncMessage<int>>([] { return 1; })); }
        catch (const std::runtime_error&) { caught = true; }
        assert(caught);
    });
    overload.join(); queue.shutdown(); queue.initialize([] {});

    for (int i = 0; i < 500; ++i) {
        auto task = std::make_shared<AESyncMessage<int>>([] { return 9; });
        std::thread execute([&] { task->execute(); });
        task->cancel(); execute.join();
        assert(task->resultFuture.wait_for(10ms) == std::future_status::ready);
        try { assert(task->getResult() == 9); } catch (const std::runtime_error&) { assert(task->isCancelled()); }
    }
    assert(ScriptJsonQuote("a\"\\\n\t") == "\"a\\\"\\\\\\u000a\\u0009\"");
    assert(MessageQueueConfig::kPendingSleepTicks == 1 && MessageQueueConfig::kEmptySleepTicks == 15);
    std::cout << "native queue: inline, queued timeout, running lifetime, time budget, shutdown, overload, 500 cancel races, JSON escaping PASS\n";
}
