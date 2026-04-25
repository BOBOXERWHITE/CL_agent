# 03 房型与床型规范

#### 关键词
`房型 / 床型 / SGL / DBL / TWN / TRP / 大床 / 双床 / 套房 / Suite / 行政房 / 家庭房 / 加床 / 婴儿床 / 连通房 / 无障碍房 / 占用人数 / 入住人数 / 加人加费`

## 1. 床型分类与床宽（行业标准）

| 中文 | 英文 | 床宽 | 备注 |
| --- | --- | --- | --- |
| 单人床 | Single | 90–100 cm | 经济型常见 |
| 小双 | Small Double | 120 cm | 欧洲常见 |
| 标准双 | Double / Full | 135–140 cm | 美式 Double |
| Queen | Queen | 150–160 cm | 美式 Queen，国内多数"大床" |
| King | King | 180–200 cm | 美式 King；欧式 Super King 200 cm |
| 加州 King | California King | 183 × 213 cm | 美式加长，腿长客人偏好 |
| 双单合一 | Twin XL Pair / Hollywood Twin | 2 × 100 cm 拼大床 | 商务酒店常用 |
| 沙发床 | Sofa Bed / Pull-out | 120–135 cm | 加床场景 |
| 婴儿床 | Crib / Cot | 60 × 120 cm | 通常免费，需提前申请 |
| 加床 | Rollaway / Extra Bed | 90 × 195 cm | 一般 ≤1 张，需付费 |
| 榻榻米 / 地铺 | Futon | — | 日式 / 韩式酒店 |

## 2. 通用房型代码

> 不同 PMS / OTA 房型代码可能不同。差旅系统 `room_type_id` 应与外部系统映射，而非自创。

| 标准代码 | 常用别名 | 说明 |
| --- | --- | --- |
| SGL | SIN / S | 单人房（1 张单人床） |
| DBL | DOU / D | 大床房（1 张 Queen/King） |
| TWN | TWO / T | 双床房（2 张单人床） |
| TPL | TRP / TRI | 三人房（3 张单或 1 大 +1 小） |
| QUAD | QUA | 四人房 |
| FAM | FAMILY | 家庭房 |
| STU | STUDIO | 一居 / 开放式 |
| SUITE | STE | 套房 |
| JST | JR / JS | 小套房 (Junior Suite) |
| EX | EXEC | 行政房 / 行政楼层房 |
| EXST | ES | 行政套房 |
| PSU | PRES / PSUITE | 总统套房 |
| ROH | RUN OF HOUSE | 不指定房型 |
| ADA | ACC | 无障碍房 |
| CON | CN | 连通房 |
| ADJ | AJ | 相邻房 |
| LOFT | LF | 阁楼 / 复式 |
| DUPLEX | DPX | 双层套房 |

## 3. 高端房型加备语义

| 加备 | 中文 | 含义 |
| --- | --- | --- |
| Deluxe | 豪华 | 房型升级 1 档 |
| Premier / Premium | 高级 | 房型升级 1 档 |
| Superior | 优质 | 比标房稍好 |
| Grand | 至尊 | 较 Deluxe 再升 |
| Executive | 行政 | 含行政楼层礼遇 |
| Club | 俱乐部 | 含 Club Lounge |
| Concierge | 礼宾 | 含礼宾接待 |
| View | 景观 | 城景 / 海景 / 山景 / 园景 |
| Pool Access | 泳池入户 | 房间直入泳池 |
| Tower / Wing | 塔楼 / 翼楼 | 区分老 / 新楼栋 |
| Garden | 花园 | 含独立花园 |
| Villa | 别墅 | 独栋 |
| Bungalow / Pavilion | 平房 / 楼阁 | 度假村独栋 |
| Overwater | 水上 | 水上别墅 |

## 4. 入住人数规则（Occupancy Rule）

差旅系统应在 `room_type` 维度记录两组字段：

| 字段 | 含义 | 示例 |
| --- | --- | --- |
| `max_adults` | 最大成人数 | 2 |
| `max_children` | 最大儿童数 | 1 |
| `max_pax_total` | 总人数上限 | 3 |
| `child_age_max` | 儿童年龄上限 | 12（部分酒店 6 / 11 / 17，需逐酒店配置） |
| `infant_age_max` | 婴儿年龄上限 | 2 |
| `extra_bed_allowed` | 是否可加床 | true |
| `extra_bed_max` | 加床最大张数 | 1 |
| `extra_bed_fee` | 加床费 | CNY 200 / 晚 |
| `crib_allowed` | 是否可放婴儿床 | true |
| `crib_fee` | 婴儿床费 | 0 |
| `breakfast_per_pax` | 含早份数（按人计） | 2 |
| `breakfast_age_free_under` | 早餐免费年龄 | 6 |

### 4.1 加人加费规则

- 多数三星 / 四星酒店：第 3 人按"加床费"或按"早餐费"收取，**不按整间房费收取**
- 高端酒店：加人无费但需控制总人数（≤套房标定）
- 经济型：双床房 2 人入住不加费；单床房第 3 人需另付"加人费"
- 海外（北美 / 欧洲）：常见做法为按人头 (per person)，2 人价 ≠ 1 人价

### 4.2 儿童规则

| 场景 | 国内典型 | 海外典型 |
| --- | --- | --- |
| 不占床 0–6 岁 | 免费 | 免费（多数欧洲） |
| 不占床 7–12 岁 | 免早 1 份；不收房费 | 部分酒店收儿童费 |
| 占床 ≥12 岁 | 视为加床 / 加人 | 视为加床 |
| 婴儿床 | 多数免费但需申请 | 多数免费 |

## 5. 特殊房型

### 5.1 无障碍房 (ADA / Accessible Room)

- 卫浴：roll-in shower、扶手、低位洗手台、紧急呼叫绳
- 房门：≥81 cm 宽
- 床高：43–60 cm
- 视听辅助：振动闹钟、闪光门铃、TTY 电话
- **预订规则**：需在订单 `accessibility_required` 标记，避免被酒店分配普通房；超售场景 ADA 房应**优先保留**
- 国内酒店多数仅配备 1–2 间无障碍房，需提前与酒店双向确认

### 5.2 连通房 (Connecting Room) vs 相邻房 (Adjoining Room)

| 类型 | 中文 | 是否有内部门 | 适用 |
| --- | --- | --- | --- |
| Connecting | 连通 | 有 | 家庭 / 同行客 |
| Adjoining | 相邻 | 无 | 仅相邻 |

- 连通房需明确 **`requires_pair_lock`**：两间房均需出售给同一住客 / 同一公司
- 大多数 OTA 不支持连通房直订，需邮件 / 直连 Special Request

### 5.3 吸烟 / 非吸烟

- 国内多数城市自 2017 年起公共场所禁烟，但部分酒店保留 1 层吸烟楼层
- 海外北美 95%+ 酒店全面禁烟，违规清洁费 USD 250–500
- 系统字段：`smoking_preference` 建议值：`non_smoking`（默认）/ `smoking` / `no_preference`

### 5.4 总统套房 / VIP 房

- **不允许在 OTA 公开售卖**（多数集团政策），仅可通过销售总监 / Sales Director 渠道直订
- 通常含管家服务、机场接送、行政酒廊全程礼遇
- 差旅政策：仅限 C-Level 或重要客户接待

## 6. 房型映射规范（差旅系统）

差旅系统对接多源数据时，建议采用三层映射：

```
external_room_code (供应商原始)
        ↓ 映射
internal_room_class (统一分类: SGL/DBL/TWN/TPL/SUITE/...)
        ↓ 映射
display_room_label (展示文本: "高级大床房 - 城景")
```

### 6.1 字段建议

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `hotel_id` | string | 酒店主键（统一 ID） |
| `external_hotel_id` | string | 供应商原始 ID |
| `external_supplier` | enum | ctrip / meituan / booking / agoda / hotelbeds / direct / ... |
| `room_type_id` | string | 内部房型主键 |
| `external_room_code` | string | 供应商房型码 |
| `internal_room_class` | enum | SGL/DBL/TWN/TPL/QUAD/STU/SUITE/JST/EX/EXST/PSU/FAM/ROH/ADA/CON/ADJ/LOFT |
| `bed_type` | enum | single/queen/king/twin/sofa/cal_king/futon |
| `bed_count` | int | 几张床 |
| `view_type` | enum | city/sea/mountain/garden/pool/courtyard/none |
| `area_sqm` | int | 面积 |
| `floor_min` | int | 楼层下限 |
| `floor_max` | int | 楼层上限 |
| `smoking` | enum | non_smoking / smoking / no_preference |
| `accessible` | bool | ADA |
| `connecting_with` | array | 连通房型 ID 列表 |
| `max_adults` | int | 最大成人 |
| `max_children` | int | 最大儿童 |
| `extra_bed_allowed` | bool |  |
| `extra_bed_fee` | money |  |

## 7. 常见映射坑点

1. **"大床 / 双床" 同一房型代码**：部分 PMS（含 Opera）会用同一 RoomType 但不同 Inventory Code，差旅系统需在 `room_type_id` 维度区分
2. **"高级"含义不一**：在 Sheraton 是 +1 档，在 W 可能 +2 档，仅靠文本无法跨集团对齐
3. **Booking.com 房型描述常含"Optional"**：如 "Choose your Bed Type"，对应 PMS 单一房型码 + 供应商侧任选
4. **携程"特惠房 / 特价房"**：实际是同一房型，仅价格码不同（参见 [04_rate_plans_and_fees.md](04_rate_plans_and_fees.md)）
5. **国际 ROH 不等于国内"不指定房型"**：海外 ROH 常被用于团队 / 不可改 / 无法升级；国内多数酒店 OTA 上的"运行房"也是 ROH
6. **海景 / City View 落差极大**：建议在 `view_type` 之外增加 `view_quality_tier`（partial / side / full）

## 8. 房间面积与含量参考（行业典型）

| 房型 | 国内典型 (㎡) | 海外典型 (㎡) |
| --- | --- | --- |
| 经济型大床 | 18–22 | 22–28 |
| 中端标准 | 25–32 | 28–34 |
| 中高端豪华 | 32–40 | 32–40 |
| 五星标准 | 40–50 | 36–48 |
| 行政房 | 45–60 | 40–55 |
| 小套房 | 55–75 | 45–65 |
| 套房 | 75–120 | 60–110 |
| 总统套房 | 200–500+ | 150–400+ |

## 9. 常见客人请求 (Special Requests) 字段

| 请求 | 字段值 | 说明 |
| --- | --- | --- |
| 高 / 低楼层 | `floor_pref=high/low` | 不保证 |
| 远 / 近电梯 | `elevator_pref=far/near` |  |
| 安静 / 房间朝向 | `quiet_pref=true` |  |
| 双枕 / 多枕 | `pillow_count=2/4` |  |
| 吸烟 / 非吸烟 | `smoking_preference` |  |
| 无障碍 | `accessibility_required` | **必须满足或拒单** |
| 连通房 | `connecting_required` | 需双订单 |
| 蜜月 / 周年 | `occasion=honeymoon/anniversary` | 触发欢迎礼遇 |
| 庆生 | `occasion=birthday` |  |
| 早入 | `early_checkin_eta` |  |
| 晚走 | `late_checkout_etd` |  |
| 孕妇 / 行动不便 | `mobility_assistance=true` |  |
| 宠物 | `pet=true` + `pet_size` | 需酒店 pet-friendly |

## 10. 与其他章节的关系

- 价格结构：见 [04_rate_plans_and_fees.md](04_rate_plans_and_fees.md)
- 早餐 / 含餐：见 [04_rate_plans_and_fees.md](04_rate_plans_and_fees.md#含餐结构)
- 数据字段规范：见 [18_data_integration_field_spec.md](18_data_integration_field_spec.md)
- 入住相关 SOP：见 [06_booking_sop.md](06_booking_sop.md)、[08_noshow_earlycheckout_latecheckin_sop.md](08_noshow_earlycheckout_latecheckin_sop.md)
