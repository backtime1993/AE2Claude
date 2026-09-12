#include "../src/PyShiftAE/CoreSDK/NativeAutomationValidation.h"
#include <cassert>
#include <iostream>
#include <limits>

using namespace NativeAutomation;
template<typename F> void rejects(F function) {
    bool failed=false;
    try { function(); } catch(const std::invalid_argument&) {failed=true;}
    assert(failed);
}

int main() {
    assert(timeFromSeconds(0).value==0);
    assert(timeFromSeconds(1.0/30).value==33333);
    assert(timeFromSeconds(-0.0000005).value==-1);
    for(double time : {0.0, 1.0/23.976, 600.123456, 3600.033333, -10800.0, 86400.0}) {
        const auto result=timeFromSeconds(time);
        assert(std::abs(result.seconds()-time)<=0.5/result.scale+1e-10);
        assert(result.scale>=10000);
    }
    rejects([] {timeFromSeconds(std::numeric_limits<double>::infinity());});
    rejects([] {timeFromSeconds(std::numeric_limits<double>::quiet_NaN());});
    rejects([] {timeFromSeconds(86400.1);});
    rejects([] {validateKeyTimes({});});
    rejects([] {validateKeyTimes({1,1});});
    rejects([] {validateKeyTimes({2,1});});
    rejects([] {validateKeyTimes({0,0.0000001});});
    rejects([] {validateKeyTimes(std::vector<double>(4097,0));});
    std::vector<double> frames;
    for(int i=0;i<4096;++i) frames.push_back(3600.0+i/29.97);
    validateKeyTimes(frames);
    std::cout<<"Native automation validation passed: finite/range, long timelines, quantization, ordering, 4096 keys\n";
}
