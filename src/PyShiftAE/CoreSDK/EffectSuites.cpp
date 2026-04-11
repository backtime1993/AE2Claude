#include "EffectSuites.h"

#include <cstdio>
#include <stdexcept>
#include <string>

namespace {

std::string jsxStringLiteral(const std::string& value) {
  std::string out;
  out.reserve(value.size() + 2);
  out.push_back('"');

  for (unsigned char ch : value) {
    switch (ch) {
    case '\\':
      out += "\\\\";
      break;
    case '"':
      out += "\\\"";
      break;
    case '\b':
      out += "\\b";
      break;
    case '\f':
      out += "\\f";
      break;
    case '\n':
      out += "\\n";
      break;
    case '\r':
      out += "\\r";
      break;
    case '\t':
      out += "\\t";
      break;
    default:
      if (ch < 0x20) {
        char escaped[7] = {};
        std::snprintf(escaped, sizeof(escaped), "\\u%04x", ch);
        out += escaped;
      } else {
        out.push_back(static_cast<char>(ch));
      }
      break;
    }
  }

  out.push_back('"');
  return out;
}

int parseEffectIndexResult(const std::string& scriptResult) {
  if (scriptResult.rfind("ERR:cannot_add:", 0) == 0) {
    return -1;
  }
  if (scriptResult.rfind("ERR:", 0) == 0 || scriptResult.empty()) {
    return -2;
  }

  try {
    int index = std::stoi(scriptResult);
    return index > 0 ? index : -2;
  } catch (const std::exception&) {
    return -2;
  }
}

} // namespace

Result<int> GetLayerNumEffects(Result<AEGP_LayerH> layerH) {
  A_long num_effectsPL = 0;
  A_Err err = A_Err_NONE;
  AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
  AEGP_LayerH layer = layerH.value;
  ERR(suites.EffectSuite4()->AEGP_GetLayerNumEffects(layer, &num_effectsPL));
  Result<int> result;
  result.value = static_cast<int>(num_effectsPL);
  result.error = err;
  return result;
}

Result<AEGP_EffectRefH> GetLayerEffectByIndex(Result<AEGP_LayerH> layerH, int effect_indexL) {
  A_Err err = A_Err_NONE;
  AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
  AEGP_LayerH layer = layerH.value;
  AEGP_EffectIndex effect_index = effect_indexL;
  AEGP_EffectRefH effectPH = NULL;
  AEGP_PluginID* pluginIDPtr = SuiteManager::GetInstance().GetPluginID();

  if (pluginIDPtr != nullptr) {
	  // Dereference the pointer to get the plugin ID
	  AEGP_PluginID  pluginID = *pluginIDPtr;
	  ERR(suites.EffectSuite4()->AEGP_GetLayerEffectByIndex(pluginID, layer, effect_index, &effectPH));
  } else {
      err = A_Err_GENERIC;
  }
  Result<AEGP_EffectRefH> result;
  result.value = effectPH;
  result.error = err;
  return result;
}

Result<AEGP_InstalledEffectKey> GetInstalledKeyFromLayerEffect(Result<AEGP_EffectRefH> effect_refH) {
  A_Err err = A_Err_NONE;
  AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
  AEGP_EffectRefH effect_ref = effect_refH.value;
  AEGP_InstalledEffectKey installed_keyP = 0;
  ERR(suites.EffectSuite4()->AEGP_GetInstalledKeyFromLayerEffect(effect_ref, &installed_keyP));
  Result<AEGP_InstalledEffectKey> result;
  result.value = installed_keyP;
  result.error = err;
  return result;
}

Result<PF_ParamDefUnion> GetEffectParamUnionByIndex(Result<AEGP_EffectRefH> effectH, int param_index) {
  A_Err err = A_Err_NONE;
  AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
  AEGP_EffectRefH effect = effectH.value;
  PF_ParamIndex param_indexP = param_index;
  PF_ParamType param_typeP = PF_Param_RESERVED;
  PF_ParamDefUnion uP0 = {};
  AEGP_PluginID* pluginIDPtr = SuiteManager::GetInstance().GetPluginID();
  if (pluginIDPtr != nullptr) {
      ERR(suites.EffectSuite4()->AEGP_GetEffectParamUnionByIndex(*pluginIDPtr, effect, param_indexP, &param_typeP, &uP0));
  } else {
      err = A_Err_GENERIC;
  }
  Result<PF_ParamDefUnion> result;
  result.value = uP0;
  result.error = err;
  return result;
}

Result<AEGP_EffectFlags> GetEffectFlags(Result<AEGP_EffectRefH> effect_refH) {
  A_Err err = A_Err_NONE;
  AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
  AEGP_EffectRefH effect_ref = effect_refH.value;
  AEGP_EffectFlags effect_flagsP = 0;
  ERR(suites.EffectSuite4()->AEGP_GetEffectFlags(effect_ref, &effect_flagsP));
  Result<AEGP_EffectFlags> result;
  result.value = effect_flagsP;
  result.error = err;
  return result;
}

Result<void> SetEffectFlags(Result<AEGP_EffectRefH> effect_refH, AEGP_EffectFlags mask, AEGP_EffectFlags effect_flags) {
  A_Err err = A_Err_NONE;
  AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
  AEGP_EffectRefH effect_ref = effect_refH.value;
  ERR(suites.EffectSuite4()->AEGP_SetEffectFlags(effect_ref, mask, effect_flags));
return Result<void>(err);
}

Result<void> ReorderEffect(Result<AEGP_EffectRefH> effect_refH, int effect_indexL) {
  A_Err err = A_Err_NONE;
  AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
  A_long effect_index = effect_indexL;
  AEGP_EffectRefH effect_ref = effect_refH.value;
  ERR(suites.EffectSuite4()->AEGP_ReorderEffect(effect_ref, effect_index));
  return Result<void>(err);
}

Result<void> EffectCallGeneric(Result<AEGP_EffectRefH> effectH, void* extraPV) {
  A_Err err = A_Err_NONE;
  AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
  A_Time timeP;
  timeP.scale = 1;
  timeP.value = 0;
  AEGP_EffectRefH effect = effectH.value;
  AEGP_PluginID* pluginIDPtr = SuiteManager::GetInstance().GetPluginID();

  if (pluginIDPtr != nullptr) {
	  // Dereference the pointer to get the plugin ID
	  AEGP_PluginID  pluginID = *pluginIDPtr;
	  ERR(suites.EffectSuite4()->AEGP_EffectCallGeneric(pluginID, effect, &timeP, PF_Cmd_COMPLETELY_GENERAL, extraPV));
	  return Result<void>(err);
  }
  return Result<void>(A_Err_GENERIC);
}

Result<void> DisposeEffect(Result<AEGP_EffectRefH> effectH) {
  A_Err err = A_Err_NONE;
  AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
  AEGP_EffectRefH effect = effectH.value;
  ERR(suites.EffectSuite4()->AEGP_DisposeEffect(effect));
  return Result<void>(err);
}

Result<AEGP_EffectRefH> ApplyEffect(Result<AEGP_LayerH> layerH, Result<AEGP_InstalledEffectKey> installed_keyZ) {
  A_Err err = A_Err_NONE;
  AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
  AEGP_LayerH layer = layerH.value;
  AEGP_EffectRefH effect_refPH = NULL;
  AEGP_InstalledEffectKey installed_key = installed_keyZ.value;
  AEGP_PluginID* pluginIDPtr = SuiteManager::GetInstance().GetPluginID();
  if (pluginIDPtr != nullptr) {
      ERR(suites.EffectSuite4()->AEGP_ApplyEffect(*pluginIDPtr, layer, installed_key, &effect_refPH));
  } else {
      err = A_Err_GENERIC;
  }
  Result<AEGP_EffectRefH> result(effect_refPH, err);
  return result;
}

Result<int> ApplyEffectByMatchName(Result<AEGP_LayerH> layerH, const std::string& matchName) {
  A_Err err = A_Err_NONE;
  AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
  AEGP_PluginID* pluginIDPtr = SuiteManager::GetInstance().GetPluginID();

  if (!pluginIDPtr || layerH.value == NULL || matchName.empty()) {
    return Result<int>(-2, A_Err_GENERIC);
  }

  AEGP_CompH parentCompH = NULL;
  AEGP_ItemH compItemH = NULL;
  A_long compItemId = 0;
  AEGP_LayerIDVal layerId = 0;

  ERR(suites.LayerSuite9()->AEGP_GetLayerParentComp(layerH.value, &parentCompH));
  if (!err) {
    ERR(suites.CompSuite11()->AEGP_GetItemFromComp(parentCompH, &compItemH));
  }
  if (!err) {
    ERR(suites.ItemSuite9()->AEGP_GetItemID(compItemH, &compItemId));
  }
  if (!err) {
    ERR(suites.LayerSuite9()->AEGP_GetLayerID(layerH.value, &layerId));
  }
  if (err != A_Err_NONE) {
    return Result<int>(-2, err);
  }

  std::string script =
    "(function(){"
    "var compId=" + std::to_string(compItemId) + ";"
    "var layerId=" + std::to_string(layerId) + ";"
    "var mn=" + jsxStringLiteral(matchName) + ";"
    "var comp=null;"
    "for(var i=1;i<=app.project.numItems;i++){"
    "var it=app.project.item(i);"
    "if(it&&it.id===compId){comp=it;break;}"
    "}"
    "if(!comp)return 'ERR:comp_not_found';"
    "var layer=null;"
    "for(var j=1;j<=comp.numLayers;j++){"
    "var ly=comp.layer(j);"
    "if(ly&&ly.id===layerId){layer=ly;break;}"
    "}"
    "if(!layer)return 'ERR:layer_not_found';"
    "var efx=layer.property('ADBE Effect Parade');"
    "if(!efx)return 'ERR:no_effect_group';"
    "if(!efx.canAddProperty(mn))return 'ERR:cannot_add:'+mn;"
    "var ef=efx.addProperty(mn);"
    "if(!ef)return 'ERR:add_failed:'+mn;"
    "return String(ef.propertyIndex);"
    "})()";

  A_Boolean scriptAvail = FALSE;
  ERR(suites.UtilitySuite6()->AEGP_IsScriptingAvailable(&scriptAvail));
  if (err != A_Err_NONE || !scriptAvail) {
    return Result<int>(-2, err != A_Err_NONE ? err : A_Err_GENERIC);
  }

  AEGP_MemHandle resultMH = nullptr;
  AEGP_MemHandle errorMH = nullptr;
  ERR(suites.UtilitySuite6()->AEGP_ExecuteScript(
    *pluginIDPtr,
    script.c_str(),
    FALSE,
    &resultMH,
    &errorMH));

  if (errorMH) {
    A_char* errorP = nullptr;
    suites.MemorySuite1()->AEGP_LockMemHandle(errorMH, (void**)&errorP);
    std::string errorStr = (errorP && errorP[0] != '\0') ? errorP : "";
    suites.MemorySuite1()->AEGP_UnlockMemHandle(errorMH);
    suites.MemorySuite1()->AEGP_FreeMemHandle(errorMH);
    if (!errorStr.empty()) {
      if (resultMH) {
        suites.MemorySuite1()->AEGP_FreeMemHandle(resultMH);
      }
      return Result<int>(-2, err != A_Err_NONE ? err : A_Err_GENERIC);
    }
  }

  std::string result;
  if (resultMH) {
    A_char* resultP = nullptr;
    suites.MemorySuite1()->AEGP_LockMemHandle(resultMH, (void**)&resultP);
    if (resultP) {
      result = resultP;
    }
    suites.MemorySuite1()->AEGP_UnlockMemHandle(resultMH);
    suites.MemorySuite1()->AEGP_FreeMemHandle(resultMH);
  }

  if (err != A_Err_NONE) {
    return Result<int>(-2, err);
  }

  return Result<int>(parseEffectIndexResult(result), A_Err_NONE);
}

Result<void> DeleteLayerEffect(Result<AEGP_EffectRefH> effect_refH) {
  A_Err err = A_Err_NONE;
  AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
  ERR(suites.EffectSuite4()->AEGP_DeleteLayerEffect(effect_refH.value));
  return Result<void>(err);
}

Result<int> GetNumInstalledEffects() {
  A_Err err = A_Err_NONE;
  A_long num_installed_effectsPL = 0;
  AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
  ERR(suites.EffectSuite4()->AEGP_GetNumInstalledEffects(&num_installed_effectsPL));
  return Result<int>(static_cast<int>(num_installed_effectsPL), err);
}

Result<AEGP_InstalledEffectKey> GetNextInstalledEffect(Result<AEGP_InstalledEffectKey> key) {
  A_Err err = A_Err_NONE;
  AEGP_InstalledEffectKey next_keyPH = 0;
  AEGP_InstalledEffectKey keyP = key.value;
  AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
  ERR(suites.EffectSuite4()->AEGP_GetNextInstalledEffect(keyP, &next_keyPH));
  return Result<AEGP_InstalledEffectKey>(next_keyPH, err);
}

Result<void> GetEffectName(AEGP_InstalledEffectKey installed_key, A_char* nameZ) {
  A_Err err = A_Err_NONE;
  AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
  ERR(suites.EffectSuite4()->AEGP_GetEffectName(installed_key, nameZ));
  return Result<void>(err);
}

Result<std::string> GetEffectMatchName(Result<AEGP_InstalledEffectKey> installed_keyZ){
  A_Err err = A_Err_NONE;
  AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
  A_char match_nameZ[AEGP_MAX_EFFECT_MATCH_NAME_SIZE] = { '\0' };
  AEGP_InstalledEffectKey key = installed_keyZ.value;
  ERR(suites.EffectSuite4()->AEGP_GetEffectMatchName(key, match_nameZ));
  std::string name = match_nameZ;
  return Result<std::string>(name, err);
}

Result<void> GetEffectCategory(Result<AEGP_InstalledEffectKey>  installed_key, A_char* categoryZ) {
  A_Err err = A_Err_NONE;
  AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
  AEGP_InstalledEffectKey installed_keyZ = installed_key.value;
  ERR(suites.EffectSuite4()->AEGP_GetEffectCategory(installed_keyZ, categoryZ));
  return Result<void>(err);
}

Result<AEGP_EffectRefH> DuplicateEffect(Result<AEGP_EffectRefH> orig_effect_refH) {
  A_Err err = A_Err_NONE;
  AEGP_EffectRefH dupe_refPH = NULL;
  AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
  ERR(suites.EffectSuite4()->AEGP_DuplicateEffect(orig_effect_refH.value, &dupe_refPH));
  Result<AEGP_EffectRefH> result(dupe_refPH, err);
  return result;
}

Result<int> NumEffectMask(Result<AEGP_EffectRefH> effect_refH) {
  A_Err err = A_Err_NONE;
  A_u_long num_masksPL = 0;
  AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
  ERR(suites.EffectSuite4()->AEGP_NumEffectMask(effect_refH.value, &num_masksPL));
  Result<int> result;
  result.value = static_cast<int>(num_masksPL);
  result.error = err;
  return result;
}

Result<AEGP_MaskIDVal> GetEffectMaskID(Result<AEGP_EffectRefH> effect_refH, int mask_indexL) {
  A_Err err = A_Err_NONE;
  AEGP_MaskIDVal id_valP = 0;
  A_u_long mask_index = mask_indexL;
  AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
  ERR(suites.EffectSuite4()->AEGP_GetEffectMaskID(effect_refH.value, mask_index, &id_valP));
  Result<AEGP_MaskIDVal> result;
  result.value = id_valP;
  result.error = err;
  return result;
}

Result<AEGP_StreamRefH> AddEffectMask(Result<AEGP_EffectRefH> effect_refH, AEGP_MaskIDVal id_val) {
  A_Err err = A_Err_NONE;
  AEGP_StreamRefH streamPH0 = NULL;
  AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
  ERR(suites.EffectSuite4()->AEGP_AddEffectMask(effect_refH.value, id_val, &streamPH0));
  Result<AEGP_StreamRefH> result(streamPH0, err);
  return result;
}

Result<void> RemoveEffectMask(Result<AEGP_EffectRefH> effect_refH, AEGP_MaskIDVal id_val) {
  A_Err err = A_Err_NONE;
  AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
  ERR(suites.EffectSuite4()->AEGP_RemoveEffectMask(effect_refH.value, id_val));
  return Result<void>(err);
}

Result<AEGP_StreamRefH> SetEffectMask(Result<AEGP_EffectRefH> effect_refH, int mask_indexL, AEGP_MaskIDVal id_val) {
  A_Err err = A_Err_NONE;
  AEGP_StreamRefH streamPH0 = NULL;
  A_u_long mask_index = mask_indexL;
  AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
  ERR(suites.EffectSuite4()->AEGP_SetEffectMask(effect_refH.value, mask_index, id_val, &streamPH0));
  Result<AEGP_StreamRefH> result(streamPH0, err);
  return result;
}






