---
name: ae2claude-bridge
description: "Use for any After Effects automation via AE2Claude bridge. Trigger on: AE, AE Beta, After Effects, 打开AE, 合成, 图层, 关键帧, 蒙版, 特效, 渲染, 表达式, 偏移, AE2Claude, PyShiftAE, ExtendScript, JSX."
---

# AE2Claude Bridge v3.0 - After Effects 自动化

## 规则

**优先走 CLI**：所有 AE 操作优先通过 `ae2claude` 命令。CLI 覆盖不到的场景（如需要在 Python 脚本中程序化调用）可用 `from ae_bridge import AEBridge` 底层方式。

```bash
ae2claude                # health check（确认 AE 在线）
ae2claude help           # 查看全部命令
ae2claude methods        # 列出全部方法签名
ae2claude call <method> [args...] [--key value]  # 调用 ae_bridge 方法
ae2claude jsx '<code>'   # 裸 JSX
ae2claude py '<code>'    # 裸 Python (PyShiftCore)
```

## 设计原则

1. **一个方法 = 一个操作** — 创建图层和设样式分开，添加效果和设属性分开
2. **Agent 负责编排** — 循环、过滤、多步组合由你（Agent）完成，bridge 不做
3. **语义化属性名** — 用 `"position"` `"opacity"` `"scale"` `"rotation"` `"anchor_point"`，不用 AE 内部路径

## 快速开始

```bash
# 查合成
ae2claude call comp_info

# 创建文本图层 + 分步设样式
ae2claude call begin_undo "My Animation"
ae2claude call add_text_layer "Hello World" Title
ae2claude call set_text_style Title --font "SourceHanSansSC-Bold" --font_size 56 --fill_color "[1,1,1]"
ae2claude call set_layer_timing Title --start 1.0 --end 5.0

# 设关键帧（统一 set_keyframes 方法，指定属性名）
ae2claude call set_keyframes Title opacity "[[1.0,0],[1.4,100],[4.7,100],[5.0,0]]"
ae2claude call set_keyframes Title position "[[1.0,[540,1450]],[1.4,[540,1400]]]"

# 缓动（每个属性单独调用）
ae2claude call apply_transform_easing Title opacity
ae2claude call apply_transform_easing Title position

# 添加效果（返回 effect_index，后续用 index 操作）
ae2claude call add_effect Title gaussian_blur        # 返回 index，如 "1"
ae2claude call set_effect_props Title 1 '{"blurriness":50}'
ae2claude call set_effect_keyframes Title 1 '{"blurriness":[[1.0,50],[1.4,0]]}'
ae2claude call apply_effect_easing Title 1 blurriness

ae2claude call add_effect Title drop_shadow          # 返回 "2"
ae2claude call set_effect_props Title 2 '{"opacity":180,"distance":3}'

ae2claude call end_undo
```

## 前置条件

1. AE 已打开 + AE2Claude 插件已加载
2. 验证: `ae2claude` 返回 `{"status": "ok", ...}`

## API 速查

运行 `ae2claude help` 查看全部分类命令，`ae2claude methods` 查看方法签名。

### 查询
```bash
ae2claude call comp_info
ae2claude call project_info
ae2claude call list_layers
ae2claude call list_comps
ae2claude call get_layer_info <name>
ae2claude call get_layer_by_id <id>
ae2claude call enumerate_effects <name>
ae2claude call list_masks <name>
ae2claude call list_comp_markers
ae2claude call list_layer_markers <name>
ae2claude call get_selected_layers
ae2claude call render_queue_info
ae2claude call list_available_effects
ae2claude call describe_effect <matchName>
```

### 属性读写（统一接口，语义属性名）
```bash
# 读
ae2claude call get_value <name> position
ae2claude call get_value <name> opacity --at_time 0.5
ae2claude call get_keyframes <name> opacity

# 写
ae2claude call set_value <name> opacity 50
ae2claude call set_value <name> position "[960,540]"
ae2claude call set_keyframes <name> position "[[0,[100,200]],[1,[500,500]]]"
ae2claude call set_keyframes <name> opacity "[[0,0],[0.5,100],[1,0]]"
ae2claude call set_keyframes <name> scale "[[0,[50,50,100]],[1,[100,100,100]]]"
ae2claude call set_keyframes <name> rotation "[[0,0],[1,360]]"
```

支持的属性名：`position`, `opacity`, `scale`, `rotation`, `anchor_point`

### 缓动（单属性，分开调用）
```bash
ae2claude call apply_transform_easing <name> opacity
ae2claude call apply_transform_easing <name> position
ae2claude call apply_transform_easing <name> scale
# Agent 要给 3 个属性加缓动？调 3 次。
```

### 创建
```bash
ae2claude call add_text_layer "文本" MyText          # 只创建，不含样式
ae2claude call set_text_style MyText --font_size 56 --fill_color "[1,0,0]"
ae2claude call set_text_content MyText "新文本"       # 改文字内容
ae2claude call add_solid MySolid "[1,0,0]"            # 纯色图层
ae2claude call add_shape_layer MyShape
ae2claude call add_shape_rect MyShape --size "[200,100]" --roundness 10
ae2claude call add_shape_fill MyShape --color "[1,0,0]"
ae2claude call create_comp NewComp 1920 1080          # 默认 30fps 10s
ae2claude call create_camera MyCam --zoom 1200
ae2claude call create_light MyLight --intensity 80
ae2claude call create_null_control Ctrl --parent_to '["Layer1","Layer2"]'
ae2claude call import_file "C:/path/to/file.mov"
```

### 效果（index-based，先 add 拿 index，再操作）
```bash
ae2claude call add_effect <name> gaussian_blur        # 返回 effect_index
ae2claude call set_effect_props <name> <idx> '{"blurriness":20}'
ae2claude call set_effect_keyframes <name> <idx> '{"blurriness":[[0,0],[1,50]]}'
ae2claude call get_effect_param <name> <idx> blurriness
ae2claude call get_effect_keyframes <name> <idx> blurriness
ae2claude call apply_effect_easing <name> <idx> blurriness
ae2claude call enumerate_effects <name>               # 查看已有效果的 index
```

已注册的效果类型（19 个）：
`gaussian_blur`, `drop_shadow`, `fill`, `glow`, `levels`, `hue_saturation`,
`brightness_contrast`, `tint`, `tritone`, `cc_toner`, `invert`, `gradient_ramp`,
`turbulent_displace`, `fractal_noise`, `radial_blur`, `camera_lens_blur`,
`mosaic`, `motion_tile`, `posterize`

### 蒙版
```bash
ae2claude call add_mask <name> "[[0,0],[500,0],[500,500],[0,500]]" --feather 10
ae2claude call list_masks <name>
ae2claude call set_mask_feather <name> 1 20
ae2claude call set_mask_opacity <name> 1 80
ae2claude call set_mask_expansion <name> 1 5
ae2claude call animate_mask_path <name> 1 "[[0,[[0,0],[100,0],[100,100]]],[1,[[10,10],[90,10],[90,90]]]]"
ae2claude call remove_mask <name> 1
```

### 图层管理
```bash
ae2claude call set_blending_mode <name> multiply
ae2claude call get_blending_mode <name>
ae2claude call set_parent child_layer parent_layer
ae2claude call remove_parent <name>
ae2claude call get_parent <name>
ae2claude call set_3d_layer <name>
ae2claude call set_layer_timing <name> --start 1.0 --end 5.0
ae2claude call set_layer_label <name> 5
ae2claude call set_layer_selected <name> true
ae2claude call deselect_all
ae2claude call rename_layer old_name new_name
ae2claude call duplicate_layer <name>
ae2claude call reorder_layer <name> 1
ae2claude call remove_layer <name>
ae2claude call center_anchor <name>
ae2claude call set_track_matte <name> matte_layer alpha
```

### Marker
```bash
ae2claude call add_comp_marker 1.0 --comment "Beat" --label 2
ae2claude call list_comp_markers
ae2claude call remove_comp_marker 1
ae2claude call add_layer_marker <name> 0.5 --comment "Hit"
ae2claude call list_layer_markers <name>
```

### Text Animator
```bash
ae2claude call add_text_animator <name> --properties '{"opacity":0,"position":[0,-20]}'
ae2claude call set_text_animator_selector <name> --start 0 --end 100 --shape smooth
ae2claude call animate_text_selector <name> --keyframes '{"offset":[[0,0],[1,100]]}'
```

### 时间
```bash
ae2claude call enable_time_remap <name>
ae2claude call set_time_remap_keyframes <name> "[[0,0],[2,1]]"
ae2claude call freeze_frame <name> 2.0
ae2claude call reverse_layer <name>
ae2claude call set_expression <name> 'property("Transform").property("Position")' "wiggle(2,50)"
ae2claude call clear_expression <name> 'property("Transform").property("Position")'
```

### 预合成
```bash
ae2claude call precompose '["Layer1","Layer2"]' PreComp
ae2claude call list_precomps
ae2claude call open_precomp <layer_name>
ae2claude call add_comp_to_comp SourceComp
```

### 渲染
```bash
ae2claude call add_to_render_queue --output_path "C:/output/render.mov"
ae2claude call set_render_output 1 "C:/output/render.mov"
ae2claude call start_render
ae2claude call render_queue_info
ae2claude call clear_render_queue
```

### 其他
```bash
ae2claude call sample_pixel 960 540              # 采样像素
ae2claude call sample_pixels "[[0,0],[960,540]]" # 批量采样
ae2claude snapshot                                # 截帧 PNG
ae2claude run 摄像机                              # 运行用户脚本
ae2claude scripts                                 # 列出全部脚本
```

### 裸 JSX（任意 ExtendScript）
```bash
ae2claude jsx 'app.project.activeItem.name'
ae2claude jsx 'app.project.activeItem.layer(1).property("Effects").numProperties'
```

## 关键规则

1. **add_effect 返回 index** — 后续 set_effect_props / apply_effect_easing 都用这个 index
2. **缓动必须独立调用** — 在关键帧设好后再调 apply_transform_easing / apply_effect_easing
3. **Scale 始终 3D** — `[sx, sy, sz]`，sz 通常为 100
4. **中文 AE 兼容** — 所有属性路径用 matchName，不用英文 display name
5. **Layer Styles [EXPERIMENTAL]** — 大部分不支持脚本，需手动 AE 菜单操作
6. **Time Remap** — 仅支持有 footage 源的图层
7. **Agent 编排** — 需要批量操作？自己 list → filter → 逐个调用，bridge 不帮你循环

## 关联 Skill

- **原画包装** — 原画素材的 AE 包装流程，依赖本 skill 进行 AE 操作
