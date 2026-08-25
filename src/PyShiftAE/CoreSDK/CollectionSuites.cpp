#include "CollectionSuites.h"

Result<std::vector<AEGP_CollectionItemV2>> GetCompSelectionItems(Result<AEGP_CompH> compH)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    AEGP_PluginID* pluginIDPtr = SuiteManager::GetInstance().GetPluginID();
    A_Err err = A_Err_NONE;
    AEGP_Collection2H collectionH = NULL;
    std::vector<AEGP_CollectionItemV2> items;

    if (pluginIDPtr == nullptr || compH.value == NULL) {
        return Result<std::vector<AEGP_CollectionItemV2>>(items, A_Err_STRUCT);
    }

    ERR(suites.CompSuite11()->AEGP_GetNewCollectionFromCompSelection(
        *pluginIDPtr, compH.value, &collectionH));

    A_u_long numItems = 0;
    ERR(suites.CollectionSuite2()->AEGP_GetCollectionNumItems(collectionH, &numItems));
    items.reserve(static_cast<size_t>(numItems));

    for (A_u_long i = 0; !err && i < numItems; ++i) {
        AEGP_CollectionItemV2 item = {};
        ERR(suites.CollectionSuite2()->AEGP_GetCollectionItemByIndex(collectionH, i, &item));

        if (!err && item.stream_refH != NULL) {
            AEGP_StreamRefH dupStreamH = NULL;
            ERR(suites.StreamSuite6()->AEGP_DuplicateStreamRef(
                *pluginIDPtr, item.stream_refH, &dupStreamH));
            item.stream_refH = dupStreamH;
        }

        if (!err) {
            items.push_back(item);
        }
    }

    if (collectionH != NULL) {
        suites.CollectionSuite2()->AEGP_DisposeCollection(collectionH);
    }

    return Result<std::vector<AEGP_CollectionItemV2>>(items, err);
}

