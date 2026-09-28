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

template<typename F> void rejectsControl(F function, const std::string& error) {
    bool failed=false;
    try { function(); } catch(const std::runtime_error& e) {
        failed=true;
        assert(std::string(e.what())==error+"; outcome=not_started");
    }
    assert(failed);
}

void layerControls() {
    for(auto type : {LayerControlType::AV,LayerControlType::Text,LayerControlType::Shape}) {
        validateLayerControls(type,{},true);
        for(const auto* flag : {"enabled","motion_blur","shy","solo","guide"})
            for(bool value : {false,true})
                validateLayerControls(type,{{flag,value}},true);
    }
    for(const auto* flag : {"audio_active","effects_active","adjustment"}) {
        for(bool value : {false,true}) {
            for(bool blend : {false,true}) {
                validateLayerControls(LayerControlType::AV,{{flag,value}},blend);
                for(auto type : {LayerControlType::Text,LayerControlType::Shape,LayerControlType::Other})
                    rejectsControl([&]{validateLayerControls(type,{{flag,value}},blend);},
                                   "control_requires_av_layer");
            }
        }
    }
    rejectsControl([]{validateLayerControls(LayerControlType::Other,{},true);},
                   "blend_mode_not_supported");
    rejectsControl([]{validateLayerControls(LayerControlType::Other,{{"shy",true}},true);},
                   "blend_mode_not_supported");
    // Camera/light/unknown types retain their existing flag-only behavior.
    validateLayerControls(LayerControlType::Other,{{"shy",true}},false);
    validateLayerControls(LayerControlType::Other,{},false);
}

int main() {
    layerControls();
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
    std::cout<<"Native automation validation passed: layer control capabilities, finite/range, long timelines, quantization, ordering, 4096 keys\n";
}
