# 08 No-Show / 早离 / 迟到 SOP

#### 关键词
`no-show / 未到 / 早离 / Early Check-out / Early Departure / 迟到 / Late Check-in / 延迟入住 / 错过入住 / 担保 / 罚金 / 续住 / Stay Over`

## 1. 总览

| 异常类型 | 触发条件 | 默认处罚 | 系统标志 |
| --- | --- | --- | --- |
| No-Show | 未在约定 ETA 之前到店 | 全程房费 + 税 | `no_show=true` |
| Early Departure | 实际离店日期早于预订 | 首晚 / 全程房费 | `early_departure=true` |
| Late Check-in | ETA > 18:00 未提供延迟入住通知 | 房间释放风险 | `late_checkin_at_risk=true` |
| Late Check-out | 离店时间晚于约定 | 加收半天 / 一晚 | `late_checkout=true` |
| Sleep Out | 不进店但保留房间 | 视协议（多数视为入住） | `sleep_out=true` |

## 2. No-Show 处理

### 2.1 No-Show 判定

**No-Show = 已担保订单 + 入住日酒店当地时间 24:00 仍未抵店**。部分酒店以 ETA 推迟 6 小时为判定线。

### 2.2 系统侧检测

```
[T-3h]   出行人未发送 ETA / 抵店签到 → 推送提醒 + 合规提示
[T+0]    入住日 14:00 — 未抵店 → 自动 ETA 询问
[T+1h]   18:00 — 未抵店且 ETA 未确认 → TMC 客服联络
[T+2h]   22:00 — 仍未抵店 → 与酒店确认是否 No-Show
[T+3h]   24:00 — 标记 No-Show，触发结算
```

### 2.3 罚金计算

```
default_noshow_fee = first_night_room_charge + tax + service_charge
特殊场景：
  - 多晚预订: 部分协议收"全程"
  - 不可退订单: 已扣全款，无追加
  - 协议价 + 月结: 直接进当月账单
  - OTA Merchant 预付: 不退，OTA 与酒店内部结算
```

### 2.4 No-Show 申诉

| 事由 | 是否可豁免 | 证明材料 |
| --- | --- | --- |
| 航班 / 高铁取消或延误 | 多数可豁免 | 航班行程单 / 12306 改签证明 |
| 突发疾病 | 视酒店 | 医院证明 |
| 不可抗力（疫情、地震、战争） | 多数可豁免 | 政府公告 / 新闻 |
| 公务紧急变更 | 视酒店 | 公司变更函 |
| 出行人个人原因 | 不豁免 |  |
| 酒店端原因 | 全额豁免 | 酒店自认 |

申诉路径：

```
出行人 → TMC → 酒店销售 / 集团客服 → 决策（48h 内）
```

## 3. Early Departure (早离)

### 3.1 判定

实际离店日期早于预订 `check_out`，且**已经办理入住**。

### 3.2 默认罚金

| 协议政策 | 罚金 |
| --- | --- |
| 多数集团 / 中端酒店 | 1 晚房费 + 税 |
| 部分高端度假村 | 全程房费 + 税 |
| 协议价（含早离豁免） | 0 |
| 不可退预付 | 不退（已扣全款） |
| 团队订单 | 视团队协议 |

### 3.3 早离申诉

| 事由 | 是否可豁免 |
| --- | --- |
| 公务变更 / 项目结束 | 视协议（部分可豁免） |
| 疾病 / 紧急回国 | 多数可豁免 |
| 客户接待变更 | 视协议 |
| 酒店服务问题 | 视服务补救（[15_complaint_handling_sop.md](15_complaint_handling_sop.md)） |

### 3.4 早离结算细节

```
情形 1 (现付): 实际离店时按实际入住夜数收费 + 早离罚金 (若有)
情形 2 (预付不可退): 不退已支付金额
情形 3 (预付可退): 退已支付 - 已入住夜数房费 - 早离罚金
情形 4 (月结): 当月账单按实际入住 + 早离罚金计入
```

## 4. Late Check-in (迟到)

### 4.1 房间保留时长

| 担保方式 | 房间保留至 |
| --- | --- |
| 信用卡担保 | 入住次日 06:00（即不丢房） |
| 公司 BTA / Direct Bill | 入住次日 06:00 |
| 现金 / 无担保 | 入住当日 18:00（部分酒店） |
| 信用住 / 免押 | 入住次日 02:00–06:00 |

### 4.2 ETA 提供时机

差旅平台应在以下时点询问 ETA：

```
[T-72h]   出单后即可填写
[T-24h]   主动推送询问
[T-3h]    强制询问 (仅经济型 / 无担保)
```

### 4.3 ETA > 18:00 (常规) / > 22:00 (经济型)

- 必须有担保
- TMC 主动告知酒店 ETA
- 邮件或电话留底
- 入住时凭确认号 + 身份核验，免重新核价

### 4.4 极晚 / 凌晨入住特殊处理

| 情形 | 处理 |
| --- | --- |
| 凌晨 02:00 后入住 | 部分酒店按"次日入住"，可能加收半天费 |
| 跨日航班延误 | 主动联络酒店锁房 |
| 同夜未到次日才到 | 第一晚仍按 No-Show 处理（除非酒店书面豁免） |

## 5. Late Check-out (延迟离店)

### 5.1 标准延退

| 客人级别 | 延退到 | 收费 |
| --- | --- | --- |
| 普通客 | 14:00 | 视酒店（多数免费） |
| 银 / 中级会员 | 14:00–16:00 | 免费 |
| 金 / 高级会员 | 16:00 | 免费 |
| 钛 / 钻石 / 行政会员 | 16:00–18:00 | 免费（部分品牌不限） |
| 协议价加值 | 16:00 | 视协议 |
| 套餐含 Late C/O | 16:00 / 18:00 | 已含 |

### 5.2 超时收费

| 超时段 | 收费 |
| --- | --- |
| 超过 14:00–18:00 | 半天房费（约 50%） |
| 超过 18:00 | 一整晚房费 |
| 超过 24:00 | 算作下一晚入住 |

### 5.3 节假日 / 满房日

满房 / 高峰期，多数酒店**不批准**延退（除高级会员 + 行政套房）。

## 6. Stay Over / Sleep Out

| 情形 | 含义 | 处理 |
| --- | --- | --- |
| Stay Over | 客人实际仍住但未离店 | 续住通知 |
| Sleep Out | 客人外出未睡店内（房间保持锁） | 默认仍按住一晚收费 |
| Day Use 转钟点 | 中途办钟点房后离开 | 视为完整一晚 |

## 7. 流程示例

### 7.1 No-Show + 不可退订单

```
出行人 → 因航班取消未抵店 → TMC 协助申诉 →
   [若豁免]: 全额退款 / 改签
   [若不豁免]: 损失全额 → 走"不可抗力" 流程 (16_force_majeure_sop) → 内部撇账
```

### 7.2 Late Check-in (凌晨 03:00)

```
出行人 → 通过 TMC 设置 ETA = 03:00 →
   TMC 致电酒店 → 酒店锁房 → 出行人凭确认号 + 护照入住 →
   早餐时间相应延后说明 → 提示 1 张早餐券 / 不浪费
```

### 7.3 Early Departure (项目提前结束)

```
出行人 → 项目方变更，提前 1 晚离店 →
   TMC 联络酒店 → 协议价（含早离豁免）→
   实际入住 4 晚（原 5 晚），无罚金 → 离店核账 → 关单
```

## 8. 系统字段建议

```yaml
checkin_state:
  expected_arrival_time_local: "2026-05-01T22:00:00+08:00"
  guaranteed_until_local: "2026-05-02T06:00:00+08:00"
  actual_arrival_time: null|"timestamp"
  late_checkin_at_risk: bool
checkout_state:
  scheduled_checkout_local: "2026-05-04T12:00:00+08:00"
  late_checkout_to_local: null|"timestamp"
  late_checkout_fee: number
  early_departure_at: null|"timestamp"
  early_departure_fee: number
exception_log:
  - type: no_show|early_departure|late_checkin|late_checkout|sleep_out
    occurred_at: "timestamp"
    fee_charged: number
    waived: bool
    waiver_reason: string
    waiver_authorized_by: string
```

## 9. 风险点

1. **多人合订 No-Show 部分人未到**：多数酒店仍收全房费，建议系统在多人订单层提示"任一人未到则全责"
2. **凌晨签到房间未锁住**：部分酒店流程不严，需 TMC 在 18:00 前主动 confirm 锁房
3. **Late C/O 与下个客人冲突**：高峰期超时易引发投诉
4. **早离剩余晚数误退**：差旅平台财务复核时需对比 PMS folio 与原订单
5. **航班变更但出行人不通知 TMC**：通过航班数据自动联动，主动询问 ETA
6. **跨时区**：海外行程，系统须按 hotel_local_tz 校验，否则误判 No-Show

## 10. 与其他章节的关系

- 取消 / 退款：[07_modification_cancellation_sop.md](07_modification_cancellation_sop.md)
- 不可抗力：[16_force_majeure_sop.md](16_force_majeure_sop.md)
- 客诉处理：[15_complaint_handling_sop.md](15_complaint_handling_sop.md)
- 担保 / 支付：[11_settlement_and_payment.md](11_settlement_and_payment.md)
