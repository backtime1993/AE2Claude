#include "ItemManager.h"
#include "../CoreSDK/RenderOptionsSuites.h"
#include "../CoreSDK/RenderSuites.h"
#include "../CoreSDK/WorldSuites.h"

#include <cmath>

namespace {
struct DownsampleFactor {
	int x;
	int y;
};

DownsampleFactor computeDownsampleFactor(float width, float height, int maxDimension)
{
	const int safeMax = maxDimension > 0 ? maxDimension : 1;
	const int rawWidth = static_cast<int>(std::lround(width));
	const int rawHeight = static_cast<int>(std::lround(height));
	const int safeWidth = rawWidth > 0 ? rawWidth : 1;
	const int safeHeight = rawHeight > 0 ? rawHeight : 1;

	DownsampleFactor factor;
	factor.x = static_cast<int>(std::ceil(static_cast<double>(safeWidth) / safeMax));
	factor.y = static_cast<int>(std::ceil(static_cast<double>(safeHeight) / safeMax));
	if (factor.x < 1) {
		factor.x = 1;
	}
	if (factor.y < 1) {
		factor.y = 1;
	}
	return factor;
}

py::array_t<uint8_t> copyRenderedWorldToArray(Result<AEGP_FrameReceiptH> receiptH)
{
	auto& worldMsg = enqueueSyncTaskQuiet(getReceiptWorld, receiptH);
	worldMsg->wait();
	auto worldH = worldMsg->getResult();

	auto& sizeMsg = enqueueSyncTaskQuiet(getSize, worldH);
	sizeMsg->wait();
	auto sz = sizeMsg->getResult();
	int w = static_cast<int>(sz.value.width);
	int h = static_cast<int>(sz.value.height);

	auto& addrMsg = enqueueSyncTaskQuiet(getBaseAddr8, worldH);
	addrMsg->wait();
	auto baseAddr = addrMsg->getResult();

	auto& rbMsg = enqueueSyncTaskQuiet(getRowBytes, worldH);
	rbMsg->wait();
	auto rowBytes = rbMsg->getResult().value;

	if (baseAddr.error != A_Err_NONE || baseAddr.value == nullptr) {
		throw std::runtime_error("Failed to get pixel data");
	}

	auto result = py::array_t<uint8_t>({ h, w, 4 });
	auto buf = result.mutable_unchecked<3>();
	uint8_t* base = reinterpret_cast<uint8_t*>(baseAddr.value);
	for (int y = 0; y < h; y++) {
		PF_Pixel8* row = reinterpret_cast<PF_Pixel8*>(base + y * rowBytes);
		for (int x = 0; x < w; x++) {
			buf(y, x, 0) = row[x].red;
			buf(y, x, 1) = row[x].green;
			buf(y, x, 2) = row[x].blue;
			buf(y, x, 3) = row[x].alpha;
		}
	}

	return result;
}
}

void Item::deleteItem()
{
	auto item = this->itemHandle_;
	if (item.value == NULL) {
		throw std::runtime_error("No active item");
	}
	auto& message = enqueueSyncTaskQuiet(DeleteItem, item);
	message->wait();

	Result<void> result = message->getResult();
	return;
}

Result<AEGP_ItemH> Item::getItemHandle()
{
return this->itemHandle_;
}


bool Item::isSelected()
{
	auto item = this->itemHandle_;
	if (item.value == NULL) {
		throw std::runtime_error("No active item");
		return false;
	}
	auto& message = enqueueSyncTaskQuiet(IsItemSelected, item);
	message->wait();

	Result<bool> result = message->getResult();
	bool isSelected = result.value;
	return isSelected;
}

void Item::setSelected(bool select)
{
	bool deselectOthers = false;
	auto item = this->itemHandle_;
	if (item.value == NULL) {
		throw std::runtime_error("No active item");
	}
	auto& message = enqueueSyncTaskQuiet(SelectItem, item, select, deselectOthers);
	message->wait();

	Result<void> result = message->getResult();
	return;
}

std::string Item::getType()
{
	auto item = this->itemHandle_;
	if (item.value == NULL) {
		throw std::runtime_error("No active item");
		return std::string{};
	}

	auto& message = enqueueSyncTaskQuiet(getItemType, item);
	message->wait();

	Result<AEGP_ItemType> result = message->getResult();
	switch (result.value) {
	case AEGP_ItemType_COMP:
		return "Comp";
	case AEGP_ItemType_FOOTAGE:
		return "Footage";
	case AEGP_ItemType_FOLDER:
		return "Folder";
	}
}

std::string Item::getName() {
	auto item = this->itemHandle_;
	if (item.value == NULL) {
		throw std::runtime_error("No active item");
		return std::string{};
	}
	auto& message = enqueueSyncTaskQuiet(getItemName, item);
	message->wait();

	Result<std::string> result = message->getResult();
	std::string name = result.value;
	return name;
}

void Item::setName(std::string name) {
	auto item = this->itemHandle_;
	if (item.value == NULL) {
		throw std::runtime_error("No active item");
	}
	auto& message = enqueueSyncTaskQuiet(setItemName, item, name);
	message->wait();

	Result<void> result = message->getResult();
}

float Item::getWidth()
{
	auto item = this->itemHandle_;
	if (item.value == NULL) {
			throw std::runtime_error("No active item");
			return 0.0f;
		}
		auto& message = enqueueSyncTaskQuiet(GetItemDimensions, item);
	message->wait();

	Result<size> result = message->getResult();

	if (result.error != A_Err_NONE) {
			throw std::runtime_error("Error getting item dimensions");
			return 0.0f;
		}

	float width = result.value.width;
	return width;
}

float Item::getHeight()
{
	auto item = this->itemHandle_;
	if (item.value == NULL) {
			throw std::runtime_error("No active item");
			return 0.0f;
		}
		auto& message = enqueueSyncTaskQuiet(GetItemDimensions, item);
	message->wait();

	Result<size> result = message->getResult();

	if (result.error != A_Err_NONE) {
			throw std::runtime_error("Error getting item dimensions");
			return 0.0f;
		}

	float height = result.value.height;
	return height;
}

float Item::getCurrentTime()
{
	auto item = this->itemHandle_;
	if (item.value == NULL) {
			throw std::runtime_error("No active item");
			return 0.0f;
		}
	auto& message = enqueueSyncTaskQuiet(GetItemCurrentTime, item);
	message->wait();

	Result<float> result = message->getResult();

	if (result.error != A_Err_NONE) {
			throw std::runtime_error("Error getting item current time");
			return 0.0f;
		}

	float time = result.value;
	return time;
}

float Item::getDuration()
{
	auto item = this->itemHandle_;
	if (item.value == NULL) {
			throw std::runtime_error("No active item");
			return 0.0f;
		}
	auto& message = enqueueSyncTaskQuiet(GetItemDuration, item);
	message->wait();

	Result<float> result = message->getResult();

	if (result.error != A_Err_NONE) {
			throw std::runtime_error("Error getting item duration");
			return 0.0f;
		}

	float time = result.value;
	return time;
}

py::array_t<uint8_t> Item::renderFramePixels(float time, int maxDimension) {
    if (time < 0) {
        try {
            time = getCurrentTime();
        } catch (...) {
            time = 0.0f;
        }
    }

    auto& roMsg = enqueueSyncTaskQuiet(getRenderOptions, itemHandle_);
    roMsg->wait();
    auto roH = roMsg->getResult();
    if (roH.error != A_Err_NONE || roH.value == NULL)
        throw std::runtime_error("Failed to get render options");

    auto& timeMsg = enqueueSyncTaskQuiet(setTime, roH, time);
    timeMsg->wait();
    roH = timeMsg->getResult();

    if (maxDimension > 0) {
        const DownsampleFactor factor = computeDownsampleFactor(getWidth(), getHeight(), maxDimension);

        auto& dsMsg = enqueueSyncTaskQuiet(setDownsampleFactor, roH, factor.x, factor.y);
        dsMsg->wait();
        roH = dsMsg->getResult();
    }

    auto& wtMsg = enqueueSyncTaskQuiet(setWorldType, roH, AEGP_WorldType_8);
    wtMsg->wait();
    roH = wtMsg->getResult();

    auto& renderMsg = enqueueSyncTaskQuiet(renderAndCheckoutFrame, roH);
    renderMsg->wait();
    auto receiptH = renderMsg->getResult();
    if (receiptH.error != A_Err_NONE || receiptH.value == NULL) {
        enqueueSyncTaskQuiet(disposeRenderOptions, roH)->wait();
        throw std::runtime_error("Failed to render frame");
    }

    py::array_t<uint8_t> result;
    try {
        result = copyRenderedWorldToArray(receiptH);
    }
    catch (...) {
        enqueueSyncTaskQuiet(checkinFrame, receiptH)->wait();
        enqueueSyncTaskQuiet(disposeRenderOptions, roH)->wait();
        throw;
    }

    enqueueSyncTaskQuiet(checkinFrame, receiptH)->wait();
    enqueueSyncTaskQuiet(disposeRenderOptions, roH)->wait();

    return result;
}

void Item::setCurrentTime(float time)
{
	auto item = this->itemHandle_;
	if (item.value == NULL) {
			throw std::runtime_error("No active item");
		}
	auto& message = enqueueSyncTaskQuiet(SetItemCurrentTime, item, time);
	message->wait();

	Result<void> result = message->getResult();

	if (result.error != A_Err_NONE) {
			throw std::runtime_error("Error setting item current time");
		}
}

float CompItem::getFrameRate()
{
auto item = this->itemHandle_;
	if (item.value == NULL) {
		throw std::runtime_error("No active item");
		return 0;
	}
	auto& message = enqueueSyncTaskQuiet(getCompFromItem, item);
	message->wait();

	Result<AEGP_CompH> result = message->getResult();

	if (result.error != A_Err_NONE) {
		throw std::runtime_error("Error getting comp from item");
		return 0;
	}

	auto& message2 = enqueueSyncTaskQuiet(GetCompFramerate, result);
	message2->wait();

	Result<float> result2 = message2->getResult();

	if (result2.error != A_Err_NONE) {
		throw std::runtime_error("Error getting frame rate");
		return 0;
	}

	float time = result2.value;
	return time;
}

void CompItem::setFrameRate(float frameRate)
{
auto item = this->itemHandle_;
	if (item.value == NULL) {
		throw std::runtime_error("No active item");
	}
	auto& message = enqueueSyncTaskQuiet(getCompFromItem, item);
	message->wait();

	Result<AEGP_CompH> result = message->getResult();

	if (result.error != A_Err_NONE) {
		throw std::runtime_error("Error getting comp from item");
		return;
	}

	auto& message2 = enqueueSyncTaskQuiet(SetCompFramerate, result, frameRate);
	message2->wait();

	Result<void> result2 = message2->getResult();

	if (result2.error != A_Err_NONE) {
		throw std::runtime_error("Error setting frame rate");
		return;
	}
}

float CompItem::getDuration()
{
auto item = this->itemHandle_;
	if (item.value == NULL) {
		throw std::runtime_error("No active item");
		return 0;
	}
	auto& message = enqueueSyncTaskQuiet(getCompFromItem, item);
	message->wait();

	Result<AEGP_CompH> result = message->getResult();

	if (result.error != A_Err_NONE) {
		throw std::runtime_error("Error getting comp from item");
		return 0;
	}

	auto& message2 = enqueueSyncTaskQuiet(GetCompWorkAreaDuration, result);
	message2->wait();

	Result<float> result2 = message2->getResult();

	if (result2.error != A_Err_NONE) {
		throw std::runtime_error("Error getting duration");
		return 0;
	}

	float time = result2.value;
	return time;
}

void CompItem::setDuration(float duration)
{
auto item = this->itemHandle_;
	if (item.value == NULL) {
		throw std::runtime_error("No active item");
	}
	auto& message = enqueueSyncTaskQuiet(getCompFromItem, item);
	message->wait();

	Result<AEGP_CompH> result = message->getResult();

	if (result.error != A_Err_NONE) {
		throw std::runtime_error("Error getting comp from item");
		return;
	}

	auto& message2 = enqueueSyncTaskQuiet(SetCompDuration, result, duration);
	message2->wait();

	Result<void> result2 = message2->getResult();

	if (result2.error != A_Err_NONE) {
		throw std::runtime_error("Error setting duration");
		return;
	}
}

void CompItem::setWidth(float width)
{
auto item = this->itemHandle_;
	if (item.value == NULL) {
		throw std::runtime_error("No active item");
	}
	auto& message = enqueueSyncTaskQuiet(getCompFromItem, item);
	message->wait();

	Result<AEGP_CompH> result = message->getResult();

	if (result.error != A_Err_NONE) {
		throw std::runtime_error("Error getting comp from item");
		return;
	}

	float height = this->getHeight();
	auto& message2 = enqueueSyncTaskQuiet(SetCompDimensions, result, width, height);
	message2->wait();

	Result<void> result2 = message2->getResult();

	if (result2.error != A_Err_NONE) {
		throw std::runtime_error("Error setting width");
		return;
	}
}

void CompItem::setHeight(float height)
{
auto item = this->itemHandle_;
	if (item.value == NULL) {
		throw std::runtime_error("No active item");
	}
	auto& message = enqueueSyncTaskQuiet(getCompFromItem, item);
	message->wait();

	Result<AEGP_CompH> result = message->getResult();

	if (result.error != A_Err_NONE) {
		throw std::runtime_error("Error getting comp from item");
		return;
	}

	auto& message2 = enqueueSyncTaskQuiet(SetCompDimensions, result, this->getWidth(), height);
	message2->wait();

	Result<void> result2 = message2->getResult();

	if (result2.error != A_Err_NONE) {
		throw std::runtime_error("Error setting height");
		return;
	}
}

std::shared_ptr<Layer> CompItem::newSolid(std::string name, float width, float height,float red, float green, float blue, float alpha,
						float duration)
{
	auto item = this->itemHandle_;

	auto& message = enqueueSyncTaskQuiet(getCompFromItem, item);
	message->wait();

	Result<AEGP_CompH> result = message->getResult();

	auto& message2 = enqueueSyncTaskQuiet(CreateSolidInComp, name, width, height, red, green, blue, alpha, result, duration);
	message2->wait();

	Result<AEGP_LayerH> result2 = message2->getResult();

	std::shared_ptr<Layer> layer = std::make_shared<Layer>(result2);
	return layer;
}

std::shared_ptr<LayerCollection> CompItem::getSelectedLayers()
{
	auto item = this->itemHandle_;
	if (item.value == NULL) {
		throw std::runtime_error("No active item");
	}
	auto& message = enqueueSyncTaskQuiet(getCompFromItem, item);
	message->wait();

	Result<AEGP_CompH> result = message->getResult();

	if (result.error != A_Err_NONE) {
		throw std::runtime_error("Error getting comp from item");
	}

	auto& message2 = enqueueSyncTaskQuiet(GetNewCollectionFromCompSelection, result);
	message2->wait();

	Result<std::vector<Result<AEGP_LayerH>>> result2 = message2->getResult();

	if (result2.error != A_Err_NONE) {
		throw std::runtime_error("Error getting selected layers");
	}

	std::vector<std::shared_ptr<Layer>> layers;	

	for (int i = 0; i < result2.value.size(); i++) {
		Layer layer = Layer(result2.value[i]);
		std::shared_ptr<Layer> layerPtr = std::make_shared<Layer>(layer);
		layers.push_back(layerPtr);
	}

	std::shared_ptr<LayerCollection> layerCollection = std::make_shared<LayerCollection>(result, layers);
	return layerCollection;
}


std::shared_ptr<LayerCollection> CompItem::getLayers()
{
	auto item = this->itemHandle_;
	if (item.value == NULL) {
		throw std::runtime_error("No active item");
	}
	auto& message = enqueueSyncTaskQuiet(getCompFromItem, item);
	message->wait();

	Result<AEGP_CompH> result = message->getResult();

	if (result.error != A_Err_NONE) {
		throw std::runtime_error("Error getting comp from item");
	}

	auto& message2 = enqueueSyncTaskQuiet(getNumLayers, result);
	message2->wait();

	Result<int> result2 = message2->getResult();

	if (result2.error != A_Err_NONE) {
		throw std::runtime_error("Error getting number of layers");
	}

	int numLayers = result2.value;

	std::vector<std::shared_ptr<Layer>> layers;

	for (int i = 0; i < numLayers; i++) { 
		auto index = i;
		auto& message3 = enqueueSyncTaskQuiet(getLayerFromComp, result, index);
		message3->wait();

		Result<AEGP_LayerH> result3 = message3->getResult();

		if (result3.error != A_Err_NONE) {
			throw std::runtime_error("Error getting layer from comp");
		}
		std::shared_ptr<Layer> layer = std::make_shared<Layer>(result3);
		layers.push_back(layer);
	}

	std::shared_ptr<LayerCollection> layerCollection = std::make_shared<LayerCollection>(result, layers);
	return layerCollection;

}


int CompItem::NumLayers() {
	auto item = this->itemHandle_;
	if (item.value == NULL) {
		throw std::runtime_error("No active item");
		return 0;
	}
	auto& message = enqueueSyncTaskQuiet(getCompFromItem, item);
	message->wait();

	Result<AEGP_CompH> result = message->getResult();

	if (result.error != A_Err_NONE) {
		throw std::runtime_error("Error getting comp from item");
		return 0;
	}

	auto& message2 = enqueueSyncTaskQuiet(getNumLayers, result);
	message2->wait();

	Result<int> result2 = message2->getResult();

	if (result2.error != A_Err_NONE) {
		throw std::runtime_error("Error getting number of layers");
		return 0;
	}

	int numLayers = result2.value;
	return numLayers;
}

float CompItem::getCurrentTime()
{
	auto item = this->itemHandle_;
	if (item.value == NULL) {
		throw std::runtime_error("No active item");
		return 0.0f;
	}

	auto& compH = enqueueSyncTaskQuiet(getCompFromItem, item);
	compH->wait();

	Result<AEGP_CompH> resultZ = compH->getResult();

	auto& frameRate = enqueueSyncTaskQuiet(GetCompFramerate, resultZ);
	frameRate->wait();

	Result<float> result = frameRate->getResult();

	auto& message = enqueueSyncTaskQuiet(GetCompItemCurrentTime, item, result.value);
	message->wait();

	Result<float> resultH = message->getResult();

	if (resultH.error != A_Err_NONE) {
		throw std::runtime_error("Error getting current time");
		return 0.0f;
	}

	float time = resultH.value;
	return time;
}

void CompItem::setCurrentTime(float time)
{
	auto item = this->itemHandle_;
	if (item.value == NULL) {
		throw std::runtime_error("No active item");
	}

	auto& compH = enqueueSyncTaskQuiet(getCompFromItem, item);
	compH->wait();

	Result<AEGP_CompH> resultZ = compH->getResult();

	auto& frameRate = enqueueSyncTaskQuiet(GetCompFramerate, resultZ);
	frameRate->wait();

	Result<float> result = frameRate->getResult();

	auto& message = enqueueSyncTaskQuiet(SetCompItemCurrentTime, item, time, result.value);
	message->wait();

	Result<void> resultH = message->getResult();

	if (resultH.error != A_Err_NONE) {
		throw std::runtime_error("Error setting current time");
		return;
	}
}

void CompItem::addLayer(std::string name, std::string path, int index)
{
	auto item = this->itemHandle_;
	if (item.value == NULL) {
		throw std::runtime_error("No active item");
	}

	auto& getComp = enqueueSyncTaskQuiet(getCompFromItem, item);
	getComp->wait();

	Result<AEGP_CompH> compH = getComp->getResult();

	auto& createfootage = enqueueSyncTaskQuiet(createFootage, path);
	createfootage->wait();

	Result<AEGP_FootageH> createFootage = createfootage->getResult();

	auto& getroot = enqueueSyncTaskQuiet(getProjectRootFolder);
	getroot->wait();

	Result<AEGP_ItemH> Root = getroot->getResult();

	auto& addtoproj = enqueueSyncTaskQuiet(addFootageToProject, createFootage, Root);
	addtoproj->wait();

	Result<AEGP_ItemH> footageItem = addtoproj->getResult();

	auto& isValid = enqueueSyncTaskQuiet(isAddLayerValid, footageItem, compH);
	isValid->wait();

	Result<bool> isvalid = isValid->getResult();

	if (isvalid.value == false) {
		throw std::runtime_error("Error adding layer");
		return;
	}

	if (isvalid.error != A_Err_NONE) {
		throw std::runtime_error("Error adding layer");
		return;
	}

	auto& addedLayer = enqueueSyncTaskQuiet(AddLayer, footageItem, compH);
	addedLayer->wait();

	Result<AEGP_LayerH> newLayer = addedLayer->getResult();

	if (newLayer.error != A_Err_NONE) {
		throw std::runtime_error("Error adding layer");
		return;
	}

	auto& changeName = enqueueSyncTaskQuiet(setLayerName, newLayer, name);
	changeName->wait();

	Result<void> result = changeName->getResult();

	if (result.error != A_Err_NONE) {
		throw std::runtime_error("Error changing layer name");
		return;
	}

	if (int(index) != -1) {
		auto& message6 = enqueueSyncTaskQuiet(changeLayerIndex, newLayer, index);
		message6->wait();

		Result<void> result6 = message6->getResult();

		if (result6.error != A_Err_NONE) {
			throw std::runtime_error("Error changing layer index");
			return;
		}
	}
}

std::string Layer::GetLayerName()
{
	auto layer = this->layerHandle_;
	if (layer.value == NULL) {
		throw std::runtime_error("No active layer");
		return std::string{};
	}
	auto& message = enqueueSyncTaskQuiet(getLayerName, layer);
	message->wait();

	Result<std::string> result = message->getResult();
	std::string	name = result.value;
	if (name == "") {
		auto& message2 = enqueueSyncTaskQuiet(getLayerSourceName, layer);
		message2->wait();

		Result<std::string> result2 = message2->getResult();
		std::string	name2 = result2.value;
		return name2;
	}
	return name;
}

std::string Layer::GetSourceName()
{
	auto layer = this->layerHandle_;
	if (layer.value == NULL) {
		throw std::runtime_error("No active layer");
		return std::string{};
	}
	auto& message = enqueueSyncTaskQuiet(getLayerSourceName, layer);
	message->wait();

	Result<std::string> result = message->getResult();
	std::string	name = result.value;
	return name;
}

void Layer::SetLayerName(std::string name)
{
	auto layer = this->layerHandle_;
	if (layer.value == NULL) {
		throw std::runtime_error("No active layer");
	}
	auto& message = enqueueSyncTaskQuiet(setLayerName, layer, name);
	message->wait();

	Result<void> result = message->getResult();
	return;
}

int Layer::index()
{
	auto layer = this->layerHandle_;
	if (layer.value == NULL) {
		throw std::runtime_error("No active layer");
		return 0;
	}
	auto& message = enqueueSyncTaskQuiet(getLayerIndex, layer);
	message->wait();

	Result<int> result = message->getResult();
	int index = result.value;
	return index;
}

//Swaps the index of the layer with the layer at the given index
void Layer::changeIndex(int index)
{
	auto layer = this->layerHandle_;
	if (layer.value == NULL) {
		throw std::runtime_error("No active layer");
	}
	auto& message = enqueueSyncTaskQuiet(changeLayerIndex, layer, index);
	message->wait();

	Result<void> result = message->getResult();
	return;
}

std::shared_ptr<Layer> Layer::duplicate()
{
	auto layer = this->layerHandle_;
	if (layer.value == NULL) {
		throw std::runtime_error("No active layer");
	}
	auto& message = enqueueSyncTaskQuiet(DuplicateLayer, layer);
	message->wait();

	Result<AEGP_LayerH> result = message->getResult();
	if (result.error != A_Err_NONE || result.value == NULL) {
		throw std::runtime_error("Failed to duplicate layer");
	}

	return std::make_shared<Layer>(result);
}


float Layer::layerTime()
{
	auto layer = this->layerHandle_;
	if (layer.value == NULL) {
		throw std::runtime_error("No active layer");
		return 0.0f;
	}
	AEGP_LTimeMode time_mode = AEGP_LTimeMode_LayerTime;
	auto& message = enqueueSyncTaskQuiet(GetLayerCurrentTime, layer, time_mode);
	message->wait();

	Result<float> result = message->getResult();
	float time = result.value;
	return time;
}

float Layer::layerCompTime()
{
	auto layer = this->layerHandle_;
	if (layer.value == NULL) {
		throw std::runtime_error("No active layer");
		return 0.0f;
	}
	AEGP_LTimeMode time_mode = AEGP_LTimeMode_CompTime;
	auto& message = enqueueSyncTaskQuiet(GetLayerCurrentTime, layer, time_mode);
	message->wait();

	Result<float> result = message->getResult();
	float time = result.value;
	return time;
}

float Layer::inPoint()
{
	auto layer = this->layerHandle_;
	if (layer.value == NULL) {
		throw std::runtime_error("No active layer");
		return 0.0f;
	}
	AEGP_LTimeMode time_mode = AEGP_LTimeMode_LayerTime;
	auto& message = enqueueSyncTaskQuiet(GetLayerInPoint, layer, time_mode);
	message->wait();

	Result<float> result = message->getResult();
	float time = result.value;
	return time;
}

float Layer::compInPoint()
{
	auto layer = this->layerHandle_;
	if (layer.value == NULL) {
		throw std::runtime_error("No active layer");
		return 0.0f;
	}
	AEGP_LTimeMode time_mode = AEGP_LTimeMode_CompTime;
	auto& message = enqueueSyncTaskQuiet(GetLayerInPoint, layer, time_mode);
	message->wait();

	Result<float> result = message->getResult();
	float time = result.value;
	return time;
}

float Layer::duration()
{
	auto layer = this->layerHandle_;
	if (layer.value == NULL) {
		throw std::runtime_error("No active layer");
		return 0.0f;
	}
	AEGP_LTimeMode time_mode = AEGP_LTimeMode_LayerTime;
	auto& message = enqueueSyncTaskQuiet(GetLayerDuration, layer, time_mode);
	message->wait();

	Result<float> result = message->getResult();
	float time = result.value;
	return time;
}

float Layer::compDuration()
{
	auto layer = this->layerHandle_;
	if (layer.value == NULL) {
		throw std::runtime_error("No active layer");
		return 0.0f;
	}
	AEGP_LTimeMode time_mode = AEGP_LTimeMode_CompTime;
	auto& message = enqueueSyncTaskQuiet(GetLayerDuration, layer, time_mode);
	message->wait();

	Result<float> result = message->getResult();
	float time = result.value;
	return time;
}

std::string Layer::getQuality()
{
	auto layer = this->layerHandle_;
	if (layer.value == NULL) {
		throw std::runtime_error("No active layer");
		return std::string{};
	}
	auto& message = enqueueSyncTaskQuiet(GetLayerQuality, layer);
	message->wait();

	Result<std::string> result = message->getResult();
	std::string quality = result.value;
	return quality;
}

void Layer::setQuality(int quality)
{
	auto layer = this->layerHandle_;
	if (layer.value == NULL) {
		throw std::runtime_error("No active layer");
	}
	if (quality != AEGP_LayerQual_NONE &&
		quality != AEGP_LayerQual_WIREFRAME &&
		quality != AEGP_LayerQual_DRAFT &&
		quality != AEGP_LayerQual_BEST) {
		throw std::invalid_argument("Invalid quality value");
	}
	auto& message = enqueueSyncTaskQuiet(SetLayerQuality, layer, quality);
	message->wait();

	Result<void> result = message->getResult();
	return;
}

void Layer::deleteLayer()
{
	auto layer = this->layerHandle_;
	if (layer.value == NULL) {
		throw std::runtime_error("No active layer");
	}
	auto& message = enqueueSyncTaskQuiet(DeleteLayer, layer);
	message->wait();

	Result<void> result = message->getResult();
	return;
}

float Layer::getOffset()
{
	auto layer = this->layerHandle_;
	if (layer.value == NULL) {
		throw std::runtime_error("No active layer");
		return 0;
	}
	auto& message = enqueueSyncTaskQuiet(GetLayerOffset, layer);
	message->wait();

	Result<float> result = message->getResult();
	float offset = result.value;
	return offset;
}

void Layer::setOffset(float offset)
{
	auto layer = this->layerHandle_;
	if (layer.value == NULL) {
		throw std::runtime_error("No active layer");
	}
	// get parent comp
	auto& message = enqueueSyncTaskQuiet(GetLayerParentComp, layer);
	message->wait();

	Result<AEGP_CompH> result = message->getResult();

	if (result.error != A_Err_NONE) {
		throw std::runtime_error("Error getting parent comp");
		return;
	}

	//get comp frame rate
	auto& message2 = enqueueSyncTaskQuiet(GetCompFramerate, result);
	message2->wait();

	Result<float> result2 = message2->getResult();

	if (result2.error != A_Err_NONE) {
		throw std::runtime_error("Error getting frame rate");
		return;
	}

	float frameRate = result2.value;
	auto& fmessage = enqueueSyncTaskQuiet(SetLayerOffset, layer, offset, frameRate);
	fmessage->wait();

	Result<void> fresult = fmessage->getResult();
	return;
}

void Layer::setFlag(LayerFlag flag, bool value)
{
	auto layer = this->layerHandle_;
	if (layer.value == NULL) {
		throw std::runtime_error("No active layer");
	}
	auto& message = enqueueSyncTaskQuiet(SetLayerFlag, layer, flag, value);
	message->wait();

	Result<void> result = message->getResult();
	return;
}

bool Layer::getFlag(LayerFlag specificFlag)
{
	auto layer = this->layerHandle_;
	if (layer.value == NULL) {
		throw std::runtime_error("No active layer");
		return false;
	}

	auto& message = enqueueSyncTaskQuiet(GetLayerFlags, layer);
	message->wait();

	Result<AEGP_LayerFlags> result = message->getResult();

	if (result.error != A_Err_NONE) {
		throw std::runtime_error("Error getting layer flags");
		return false;
	}

	AEGP_LayerFlags combinedFlags = result.value;

	// Check if the specific flag is set in the combined flags
	return (combinedFlags & specificFlag) != 0;
}

Result<AEGP_LayerH> Layer::getLayerHandle()
{
return this->layerHandle_;
}

py::array_t<uint8_t> Layer::renderFramePixels(float time, int maxDimension)
{
	if (time < 0) {
		try {
			time = layerCompTime();
		}
		catch (...) {
			time = 0.0f;
		}
	}

	auto& roMsg = enqueueSyncTaskQuiet(getLayerRenderOptions, layerHandle_);
	roMsg->wait();
	auto roH = roMsg->getResult();
	if (roH.error != A_Err_NONE || roH.value == NULL) {
		throw std::runtime_error("Failed to get layer render options");
	}

	auto& timeMsg = enqueueSyncTaskQuiet(setLayerTime, roH, time);
	timeMsg->wait();
	roH = timeMsg->getResult();

	if (maxDimension > 0) {
		float width = 1.0f;
		float height = 1.0f;
		try {
			auto source = getSource();
			if (source) {
				width = source->getWidth();
				height = source->getHeight();
			}
		}
		catch (...) {}

		const DownsampleFactor factor = computeDownsampleFactor(width, height, maxDimension);
		auto& dsMsg = enqueueSyncTaskQuiet(setLayerDownsampleFactor, roH, factor.x, factor.y);
		dsMsg->wait();
		roH = dsMsg->getResult();
	}

	auto& wtMsg = enqueueSyncTaskQuiet(setLayerWorldType, roH, AEGP_WorldType_8);
	wtMsg->wait();
	roH = wtMsg->getResult();

	auto& renderMsg = enqueueSyncTaskQuiet(renderAndCheckoutLayerFrame, roH);
	renderMsg->wait();
	auto receiptH = renderMsg->getResult();
	if (receiptH.error != A_Err_NONE || receiptH.value == NULL) {
		enqueueSyncTaskQuiet(disposeLayerRenderOptions, roH)->wait();
		throw std::runtime_error("Failed to render layer frame");
	}

	py::array_t<uint8_t> result;
	try {
		result = copyRenderedWorldToArray(receiptH);
	}
	catch (...) {
		enqueueSyncTaskQuiet(checkinFrame, receiptH)->wait();
		enqueueSyncTaskQuiet(disposeLayerRenderOptions, roH)->wait();
		throw;
	}

	enqueueSyncTaskQuiet(checkinFrame, receiptH)->wait();
	enqueueSyncTaskQuiet(disposeLayerRenderOptions, roH)->wait();

	return result;
}

void Layer::addEffect(std::shared_ptr<CustomEffect>  effect)
{
	if (effect == NULL) {
		throw std::invalid_argument("Invalid effect");
		return;
	}
	void* effectPtr = reinterpret_cast<void*>(effect.get());
	auto layer = this->layerHandle_;
	if (layer.value == NULL) {
		throw std::runtime_error("No active layer");
	}

	auto& message = enqueueSyncTaskQuiet(GetNumInstalledEffects);
	message->wait();

	Result<int> result = message->getResult();

	if (result.error != A_Err_NONE) {
		throw std::runtime_error("Error getting number of installed effects");
		return;
	}

	int numEffects = result.value;
	Result<AEGP_InstalledEffectKey> effectKey;
	effectKey.value = 0;
	effectKey.error = A_Err_NONE;
	for (int i = 0; i < numEffects; i++) {
		auto index = i;
		auto& getEffect = enqueueSyncTaskQuiet(GetNextInstalledEffect, effectKey);
		getEffect->wait();

		Result<AEGP_InstalledEffectKey> nextKey = getEffect->getResult();

		if (nextKey.error != A_Err_NONE) {
			throw std::runtime_error("Error getting next installed effect");
			return;
		}

		effectKey = nextKey;

		auto& getEffectName = enqueueSyncTaskQuiet(GetEffectMatchName, effectKey);
		getEffectName->wait();

		Result<std::string> effectName = getEffectName->getResult();

		if (effectName.error != A_Err_NONE) {
			throw std::runtime_error("Error getting effect name");
		}

		if (effectName.value == "ADBE Skeleton") {
			auto& addEffect = enqueueSyncTaskQuiet(ApplyEffect, layer, effectKey);
			addEffect->wait();

			Result<AEGP_EffectRefH> effectRef = addEffect->getResult();

			if (effectRef.error != A_Err_NONE) {
				throw std::runtime_error("Error adding effect");
			}

			auto& sendEffect = enqueueSyncTaskQuiet(EffectCallGeneric, effectRef, effectPtr);
			sendEffect->wait();

			Result<void> result = sendEffect->getResult();

			if (result.error != A_Err_NONE) {
				throw std::runtime_error("Error sending effect");
			}
		}
	}


}

std::shared_ptr<Item> Layer::getSource()
{
	//Result<AEGP_ItemH> getLayerSourceItem(Result<AEGP_LayerH> layerH);
	auto layer = this->layerHandle_;
	if (layer.value == NULL) {
		throw std::runtime_error("No active layer");
	}
	auto& message = enqueueSyncTaskQuiet(getLayerSourceItem, layer);
	message->wait();

	Result<AEGP_ItemH> result = message->getResult();

	//get item type
	auto& message2 = enqueueSyncTaskQuiet(getItemType, result);
	message2->wait();

	Result<AEGP_ItemType> result2 = message2->getResult();

	if (result2.error != A_Err_NONE) {
		throw std::runtime_error("Error getting item type");
	}

	if (result2.value == AEGP_ItemType_FOOTAGE) {
		std::shared_ptr<FootageItem> footageItem = std::make_shared<FootageItem>(result);
		return footageItem;
	}
	else if (result2.value == AEGP_ItemType_COMP) {
		std::shared_ptr<CompItem> compItem = std::make_shared<CompItem>(result);
		return compItem;
	}
	else if (result2.value == AEGP_ItemType_FOLDER) {
		std::shared_ptr<FolderItem> folderItem = std::make_shared<FolderItem>(result);
		return folderItem;
	}
	else {
		std::shared_ptr<Item> item = std::make_shared<Item>(result);
		return item;
	}
}


std::shared_ptr<ItemCollection> FolderItem::ChildItems()
{
	auto item = this->itemHandle_;
	if (item.value == NULL) {
		throw std::runtime_error("No active item");
	}

	Result<AEGP_ItemH> itemH = item;
	std::shared_ptr<ItemCollection> itemCollection = std::make_shared<ItemCollection>(itemH);

	return itemCollection;

}


void LayerCollection::removeLayerFromCollection(Layer layerHandle)
{
	auto& layer = layerHandle.getLayerHandle();
	if (layer.value == NULL) {
		throw std::runtime_error("No active layer");
	}
	layerHandle.deleteLayer();
}

void LayerCollection::RemoveLayerByIndex(int index)
{
	auto& layers = this->layers_;
	if (index < 0 || index >= layers.size()) {
		throw std::invalid_argument("Invalid index");
	}
	auto& layer = layers[index];

	layer->deleteLayer();

}


std::string LayerCollection::getCompName() 
{
	auto comp = this->compHandle_;
	if (comp.value == NULL) {
		throw std::runtime_error("No active comp");
		return std::string{};
	}
	auto& compmessage = enqueueSyncTaskQuiet(GetItemFromComp, comp);
	compmessage->wait();

	Result<AEGP_ItemH> item = compmessage->getResult();

	if (item.error != A_Err_NONE) {
	throw std::runtime_error("Error getting item from comp");
	return std::string{};
	}

	auto& message = enqueueSyncTaskQuiet(getItemName, item);
	message->wait();

	Result<std::string> result = message->getResult();

	std::string info = "Layers for Composition: " + result.value;

	return info;

}

std::shared_ptr<Layer> LayerCollection::addLayerToCollection(Item itemHandle, int index) {
	auto result = itemHandle.getItemHandle();
	if (result.error != A_Err_NONE) {
		throw std::runtime_error("Error getting item handle");
		return std::make_shared<Layer>(Result<AEGP_LayerH>{});
	}

	auto comp = this->compHandle_;
	Result<AEGP_CompH> compH = comp;
	if (compH.value == NULL) {
		throw std::runtime_error("No active comp");
		return std::make_shared<Layer>(Result<AEGP_LayerH>{});
	}


	if (compH.error != A_Err_NONE) {
		throw std::runtime_error("Error getting comp handle");
		return std::make_shared<Layer>(Result<AEGP_LayerH>{});
	}

	auto& isValid = enqueueSyncTaskQuiet(isAddLayerValid, result, compH);
	isValid->wait();

	Result<bool> isvalid = isValid->getResult();

	if (isvalid.value == false) {
		throw std::runtime_error("Error adding layer");
		return std::make_shared<Layer>(Result<AEGP_LayerH>{});
	}

	if (isvalid.error != A_Err_NONE) {
		throw std::runtime_error("Error adding layer");
		return std::make_shared<Layer>(Result<AEGP_LayerH>{});
	}

	auto& addedLayer = enqueueSyncTaskQuiet(AddLayer, result, compH);

	addedLayer->wait();

	Result<AEGP_LayerH> newLayer = addedLayer->getResult();

	if (newLayer.error != A_Err_NONE) {
		throw std::runtime_error("Error adding layer");
		return std::make_shared<Layer>(Result<AEGP_LayerH>{});
	}

	if (int(index) != -1) {
		auto& message6 = enqueueSyncTaskQuiet(changeLayerIndex, newLayer, index);
		message6->wait();

		Result<void> result6 = message6->getResult();

		if (result6.error != A_Err_NONE) {
			throw std::runtime_error("Error changing layer index");
			return std::make_shared<Layer>(Result<AEGP_LayerH>{});
		}
	}

	std::shared_ptr<Layer> layer = std::make_shared<Layer>(newLayer);
	return layer;
}

std::vector<std::shared_ptr<Item>> ItemCollection::getItems()
{
	std::vector<std::shared_ptr<Item>> items = {};
	auto item = this->itemHandle_;

	Result<AEGP_ItemH> itemhandle = item;

	// Check if the current folder item is valid
	if (itemhandle.value == NULL) {
		throw std::runtime_error("No active item");
	}
	
	auto& projectMessage = enqueueSyncTaskQuiet(getProject);
	projectMessage->wait();

	Result<AEGP_ProjectH> projectResult = projectMessage->getResult();

	Result<AEGP_ItemH> currentItemResult = itemhandle;

	while (currentItemResult.value != NULL) {
		// Check if the current item is a child of the folder
		auto& message = enqueueSyncTaskQuiet(GetItemParentFolder, currentItemResult);
		message->wait();

		Result<AEGP_ItemH> parentItemH = message->getResult();

		if (parentItemH.value == itemhandle.value) {
			// Get the type of the current item
			auto& typeMessage = enqueueSyncTaskQuiet(getItemType, currentItemResult);
			typeMessage->wait();
			Result<AEGP_ItemType> itemTypeResult = typeMessage->getResult();
			if (itemTypeResult.error != A_Err_NONE) {
				throw std::runtime_error("Error getting item type");
			}

			// Add the current item to the list based on its type
			switch (itemTypeResult.value) {
			case AEGP_ItemType_FOLDER:
				items.push_back(std::make_shared<FolderItem>(currentItemResult));
				break;
			case AEGP_ItemType_FOOTAGE:
				items.push_back(std::make_shared<FootageItem>(currentItemResult));
				break;
			case AEGP_ItemType_COMP:
				items.push_back(std::make_shared<CompItem>(currentItemResult));
				break;
				// Handle other types as needed
			}
		}

		// Get the next project item
		auto& nextItemMessage = enqueueSyncTaskQuiet(GetNextProjItem, projectResult, currentItemResult);
		nextItemMessage->wait();
		currentItemResult = nextItemMessage->getResult();
	}

	return items;
}

std::string FootageItem::getPath()
{
	auto item = this->itemHandle_;
	if (item.value == NULL) {
		throw std::runtime_error("No active item");
		return std::string{};
	}

	auto& curTime = enqueueSyncTaskQuiet(GetItemCurrentTime, item);
	curTime->wait();

	Result<float> time = curTime->getResult();

	if (time.error != A_Err_NONE) {
		throw std::runtime_error("Error getting current time");
		return std::string{};
	}

	auto& message = enqueueSyncTaskQuiet(GetMainFootageFromItem, item);
	message->wait();

	Result<AEGP_FootageH> result = message->getResult();

	if (result.error != A_Err_NONE) {
		throw std::runtime_error("Error getting main footage from item");
		return std::string{};
	}

	auto& message2 = enqueueSyncTaskQuiet(GetFootagePath, result, time.value, AEGP_FOOTAGE_MAIN_FILE_INDEX);
	message2->wait();

	Result<std::string> result2 = message2->getResult();

	if (result2.error != A_Err_NONE) {
		throw std::runtime_error("Error getting footage path");
		return std::string{};
	}

	std::string result2String = result2.value;
	return result2String;


}

void FootageItem::replaceWithNewSource(std::string name, std::string path)
{
	auto& Item = this->itemHandle_;
	if (Item.value == NULL) {
		throw std::runtime_error("No active item");
		return;
	}

	auto& createfootage = enqueueSyncTaskQuiet(createFootage, path);
	createfootage->wait();

	Result<AEGP_FootageH> createFootage = createfootage->getResult();

	if (createFootage.error != A_Err_NONE) {
		throw std::runtime_error("Error creating footage");
		return;
	}

	auto& replace = enqueueSyncTaskQuiet(ReplaceItemMainFootage, createFootage, Item);
	replace->wait();

	Result<AEGP_ItemH> result = replace->getResult();
	Item = result;

}

// ── Layer Phase 2 ──

std::shared_ptr<Layer> Layer::getParentLayer() {
    auto& msg = enqueueSyncTaskQuiet(GetLayerParent, layerHandle_);
    msg->wait();
    Result<AEGP_LayerH> result = msg->getResult();
    if (result.error != A_Err_NONE || result.value == NULL) return nullptr;
    return std::make_shared<Layer>(result);
}

void Layer::setParentLayer(std::shared_ptr<Layer> parent) {
    AEGP_LayerH parentH = parent ? parent->getLayerHandle().value : NULL;
    auto& msg = enqueueSyncTaskQuiet(SetLayerParent, layerHandle_, parentH);
    msg->wait();
}

void Layer::removeParent() {
    auto& msg = enqueueSyncTaskQuiet(SetLayerParent, layerHandle_, (AEGP_LayerH)NULL);
    msg->wait();
}

int Layer::getLabel() {
    auto& msg = enqueueSyncTaskQuiet(GetLayerLabel, layerHandle_);
    msg->wait();
    return static_cast<int>(msg->getResult().value);
}

void Layer::setLabel(int label) {
    auto& msg = enqueueSyncTaskQuiet(SetLayerLabel, layerHandle_, static_cast<AEGP_LabelID>(label));
    msg->wait();
}

int Layer::getLayerID() {
    auto& msg = enqueueSyncTaskQuiet(GetLayerID, layerHandle_);
    msg->wait();
    return msg->getResult().value;
}

bool Layer::isLayer3D() {
    auto& msg = enqueueSyncTaskQuiet(IsLayer3D, layerHandle_);
    msg->wait();
    return msg->getResult().value != 0;
}

// ── CompItem Phase 2 ──

std::shared_ptr<Layer> CompItem::addSolid(std::string name, float w, float h,
                                           float r, float g, float b, float a, float dur) {
    auto& compMsg = enqueueSyncTaskQuiet(getCompFromItem, itemHandle_);
    compMsg->wait();
    Result<AEGP_CompH> compH = compMsg->getResult();

    auto& msg = enqueueSyncTaskQuiet(CreateSolidInComp, name, static_cast<int>(w), static_cast<int>(h), r, g, b, a, compH, dur);
    msg->wait();
    Result<AEGP_LayerH> result = msg->getResult();
    if (result.error != A_Err_NONE || result.value == NULL)
        throw std::runtime_error("Failed to create solid layer");
    return std::make_shared<Layer>(result);
}

std::shared_ptr<Layer> CompItem::addNull(std::string name, float dur) {
    auto& compMsg = enqueueSyncTaskQuiet(getCompFromItem, itemHandle_);
    compMsg->wait();
    Result<AEGP_CompH> compH = compMsg->getResult();

    auto& msg = enqueueSyncTaskQuiet(CreateNullInComp, name, compH, dur);
    msg->wait();
    Result<AEGP_LayerH> result = msg->getResult();
    if (result.error != A_Err_NONE || result.value == NULL)
        throw std::runtime_error("Failed to create null layer");
    return std::make_shared<Layer>(result);
}

std::shared_ptr<Layer> CompItem::addCamera(std::string name, float x, float y) {
    auto& compMsg = enqueueSyncTaskQuiet(getCompFromItem, itemHandle_);
    compMsg->wait();
    Result<AEGP_CompH> compH = compMsg->getResult();

    auto& msg = enqueueSyncTaskQuiet(CreateCameraInComp, name, x, y, compH);
    msg->wait();
    Result<AEGP_LayerH> result = msg->getResult();
    if (result.error != A_Err_NONE || result.value == NULL)
        throw std::runtime_error("Failed to create camera layer");
    return std::make_shared<Layer>(result);
}

std::shared_ptr<Layer> CompItem::addLight(std::string name, float x, float y) {
    auto& compMsg = enqueueSyncTaskQuiet(getCompFromItem, itemHandle_);
    compMsg->wait();
    Result<AEGP_CompH> compH = compMsg->getResult();

    auto& msg = enqueueSyncTaskQuiet(CreateLightInComp, name, x, y, compH);
    msg->wait();
    Result<AEGP_LayerH> result = msg->getResult();
    if (result.error != A_Err_NONE || result.value == NULL)
        throw std::runtime_error("Failed to create light layer");
    return std::make_shared<Layer>(result);
}

std::shared_ptr<Layer> CompItem::addText(bool select) {
    auto& compMsg = enqueueSyncTaskQuiet(getCompFromItem, itemHandle_);
    compMsg->wait();
    Result<AEGP_CompH> compH = compMsg->getResult();

    auto& msg = enqueueSyncTaskQuiet(CreateTextLayerInComp, compH, select);
    msg->wait();
    Result<AEGP_LayerH> result = msg->getResult();
    if (result.error != A_Err_NONE || result.value == NULL)
        throw std::runtime_error("Failed to create text layer");
    return std::make_shared<Layer>(result);
}

std::shared_ptr<Layer> CompItem::addShape() {
    auto& compMsg = enqueueSyncTaskQuiet(getCompFromItem, itemHandle_);
    compMsg->wait();
    Result<AEGP_CompH> compH = compMsg->getResult();

    auto& msg = enqueueSyncTaskQuiet(CreateVectorLayerInComp, compH);
    msg->wait();
    Result<AEGP_LayerH> result = msg->getResult();
    if (result.error != A_Err_NONE || result.value == NULL)
        throw std::runtime_error("Failed to create shape layer");
    return std::make_shared<Layer>(result);
}

// ── CompItem Phase 3 ──

std::vector<float> CompItem::getBGColor() {
    auto& compMsg = enqueueSyncTaskQuiet(getCompFromItem, itemHandle_);
    compMsg->wait();
    auto compH = compMsg->getResult();
    auto& msg = enqueueSyncTaskQuiet(GetCompBGColor, compH);
    msg->wait();
    auto result = msg->getResult();
    return {static_cast<float>(result.value.redF), static_cast<float>(result.value.greenF),
            static_cast<float>(result.value.blueF), static_cast<float>(result.value.alphaF)};
}

void CompItem::setBGColor(float r, float g, float b) {
    auto& compMsg = enqueueSyncTaskQuiet(getCompFromItem, itemHandle_);
    compMsg->wait();
    auto& msg = enqueueSyncTaskQuiet(SetCompBGColor, compMsg->getResult(), r, g, b, 1.0f);
    msg->wait();
}

float CompItem::getWorkAreaStart() {
    auto& compMsg = enqueueSyncTaskQuiet(getCompFromItem, itemHandle_);
    compMsg->wait();
    auto& msg = enqueueSyncTaskQuiet(GetCompWorkAreaStart, compMsg->getResult());
    msg->wait();
    return msg->getResult().value;
}

float CompItem::getWorkAreaDuration() {
    auto& compMsg = enqueueSyncTaskQuiet(getCompFromItem, itemHandle_);
    compMsg->wait();
    auto& msg = enqueueSyncTaskQuiet(GetCompWorkAreaDuration, compMsg->getResult());
    msg->wait();
    return msg->getResult().value;
}

void CompItem::setWorkArea(float start, float duration) {
    auto& compMsg = enqueueSyncTaskQuiet(getCompFromItem, itemHandle_);
    compMsg->wait();
    auto& msg = enqueueSyncTaskQuiet(SetCompWorkAreaStartAndDuration, compMsg->getResult(), start, duration);
    msg->wait();
}

float CompItem::getDisplayStartTime() {
    auto& compMsg = enqueueSyncTaskQuiet(getCompFromItem, itemHandle_);
    compMsg->wait();
    auto& msg = enqueueSyncTaskQuiet(GetCompDisplayStartTime, compMsg->getResult());
    msg->wait();
    return msg->getResult().value;
}

void CompItem::setDisplayStartTime(float time) {
    auto& compMsg = enqueueSyncTaskQuiet(getCompFromItem, itemHandle_);
    compMsg->wait();
    auto& msg = enqueueSyncTaskQuiet(SetCompDisplayStartTime, compMsg->getResult(), time);
    msg->wait();
}

std::shared_ptr<CompItem> CompItem::duplicateComp() {
    auto& compMsg = enqueueSyncTaskQuiet(getCompFromItem, itemHandle_);
    compMsg->wait();
    auto& msg = enqueueSyncTaskQuiet(DuplicateComp, compMsg->getResult());
    msg->wait();
    auto newCompH = msg->getResult();
    if (newCompH.error != A_Err_NONE || newCompH.value == NULL)
        throw std::runtime_error("Failed to duplicate comp");
    auto& itemMsg = enqueueSyncTaskQuiet(GetItemFromComp, newCompH);
    itemMsg->wait();
    return std::make_shared<CompItem>(itemMsg->getResult());
}

py::array_t<uint8_t> CompItem::renderFramePixels(float time, int maxDimension) {
    return Item::renderFramePixels(time, maxDimension);
}

// ── Layer Phase 3 ──

int Layer::getTransferMode() {
    auto& msg = enqueueSyncTaskQuiet(GetLayerTransferMode, layerHandle_);
    msg->wait();
    return static_cast<int>(msg->getResult().value.mode);
}

void Layer::setTransferMode(int mode) {
    AEGP_LayerTransferMode tm;
    tm.mode = static_cast<PF_TransferMode>(mode);
    tm.flags = 0;
    tm.track_matte = AEGP_TrackMatte_NO_TRACK_MATTE;
    auto& msg = enqueueSyncTaskQuiet(SetLayerTransferMode, layerHandle_, tm);
    msg->wait();
}

float Layer::getStretch() {
    auto& msg = enqueueSyncTaskQuiet(GetLayerStretch, layerHandle_);
    msg->wait();
    return msg->getResult().value;
}

int Layer::getObjectType() {
    auto& msg = enqueueSyncTaskQuiet(GetLayerObjectType, layerHandle_);
    msg->wait();
    return static_cast<int>(msg->getResult().value);
}

int Layer::getSamplingQuality() {
    auto& msg = enqueueSyncTaskQuiet(GetLayerSamplingQuality, layerHandle_);
    msg->wait();
    return static_cast<int>(msg->getResult().value);
}

void Layer::setSamplingQuality(int quality) {
    auto& msg = enqueueSyncTaskQuiet(SetLayerSamplingQuality, layerHandle_, static_cast<AEGP_LayerSamplingQuality>(quality));
    msg->wait();
}

float Layer::convertCompToLayerTime(float compTime) {
    auto& msg = enqueueSyncTaskQuiet(ConvertCompToLayerTime, layerHandle_, compTime);
    msg->wait();
    return msg->getResult().value;
}

float Layer::convertLayerToCompTime(float layerTime) {
    auto& msg = enqueueSyncTaskQuiet(ConvertLayerToCompTime, layerHandle_, layerTime, 24.0f);
    msg->wait();
    return msg->getResult().value;
}
