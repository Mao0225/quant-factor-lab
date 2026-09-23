# 因子生成与动态选股研究流程图

本文档整理因子生成、质量评价、标准化回测、市场状态识别、动态因子选择、组合构建及强化学习反馈闭环等研究流程。图中实线表示当前研究主流程，虚线表示规划中的扩展环节。

## 图1 研究总体框架

```mermaid
flowchart LR
    A["研究问题与目标"] --> B["A股日频数据"]
    B --> C["候选因子生成"]
    C --> D["单因子质量评价"]
    D --> E{"是否达到质量门槛"}
    E -->|否| C
    E -->|是| F["单因子标准化回测"]
    F --> G["筛选、去重与因子登记"]
    G --> H["合格因子库"]
    H --> I["市场状态识别"]
    I --> J["动态因子选择"]
    J --> K["多因子 Alpha 合成"]
    K --> L["股票组合构建"]
    L --> M["交易执行与组合回测"]
    M --> N["收益、风险与稳健性评价"]
    N -.->|完整闭环扩展| C

    classDef input fill:#eef4fa,stroke:#315b7d,color:#172b3a;
    classDef method fill:#e8f0f7,stroke:#315b7d,color:#172b3a;
    classDef decision fill:#fff7e6,stroke:#8a6823,color:#3d321d;
    classDef output fill:#edf5ef,stroke:#427451,color:#17351f;

    class A,B input;
    class C,D,F,G,I,J,K,L,M method;
    class E decision;
    class H,N output;
```

## 图2 数据与研究样本构建

```mermaid
flowchart TB
    A["原始A股日频数据<br/>2021-06-18—2026-06-16"] --> B["主数据集<br/>5432只股票 · 5,990,248条记录"]
    B --> C["47个标准化字段"]

    C --> C1["价格字段<br/>open、close、high、low、ycp"]
    C --> C2["成交与流动性字段<br/>volume、amount、TurnoverRate"]
    C --> C3["涨跌与交易状态字段<br/>ChangePCT、Ifsuspend等"]
    C --> C4["技术指标字段<br/>MA、EMA、MACD、KDJ等"]
    C --> C5["股票与日期标识字段<br/>code、date、market_code等"]

    B --> D["流动性与数据覆盖筛选"]
    D --> E["liquid_500股票池<br/>500只股票"]
    E --> F["PPO研究面板<br/>38个因子输入字段"]
    F --> G["20个交易日未来收益标签"]

    F --> H1["训练期<br/>2022-01-14—2024-07-26"]
    F --> H2["验证期<br/>2024-01-25—2025-07-28"]
    F --> H3["测试期<br/>2025-01-27—2026-06-12"]

    classDef source fill:#eef4fa,stroke:#315b7d,color:#172b3a;
    classDef field fill:#f5f7f9,stroke:#647581,color:#172b3a;
    classDef sample fill:#edf5ef,stroke:#427451,color:#17351f;

    class A,B,C source;
    class C1,C2,C3,C4,C5 field;
    class D,E,F,G,H1,H2,H3 sample;
```

## 图3 PPO候选因子生成机制

```mermaid
flowchart TB
    A["研究数据与字段集合"] --> B["构造因子表达式环境"]
    B --> C["初始化 Maskable PPO 策略"]

    C --> D["状态<br/>当前表达式结构、长度与可选动作"]
    D --> E["动作掩码<br/>排除语法不合法动作"]
    E --> F{"选择下一动作"}

    F --> F1["选择数据字段"]
    F --> F2["选择一元或二元操作符"]
    F --> F3["选择时间窗口等参数"]

    F1 --> G["更新表达式状态"]
    F2 --> G
    F3 --> G

    G --> H{"表达式是否完整"}
    H -->|否| D
    H -->|是| I["形成候选因子表达式"]

    I --> J["快速因子计算"]
    J --> K["计算IC、Rank IC、ICIR与Coverage"]
    K --> L["构造PPO奖励"]
    L --> M["优势估计与策略更新"]
    M --> D

    K --> N{"候选是否合格"}
    N -->|是| O["加入候选因子集合"]
    N -->|否| P["记录失败原因"]
    P --> D

    classDef state fill:#eef4fa,stroke:#315b7d,color:#172b3a;
    classDef action fill:#e8f0f7,stroke:#315b7d,color:#172b3a;
    classDef decision fill:#fff7e6,stroke:#8a6823,color:#3d321d;
    classDef result fill:#edf5ef,stroke:#427451,color:#17351f;

    class A,B,C,D,E,G,I,J,K,L,M state;
    class F1,F2,F3 action;
    class F,H,N decision;
    class O,P result;
```

## 图4 单因子质量评价流程

```mermaid
flowchart LR
    A["候选因子表达式"] --> B["表达式语法与操作符校验"]
    B --> C{"是否可以执行"}
    C -->|否| D["拒绝并记录错误类型"]
    C -->|是| E["计算日期×股票因子值矩阵"]

    E --> F["缺失值、极端值与覆盖率检查"]
    F --> G["构造未来20日收益标签"]
    G --> H["按日期进行横截面对齐"]

    H --> I1["Pearson IC"]
    H --> I2["Rank IC"]
    H --> I3["ICIR"]
    H --> I4["Coverage"]
    H --> I5["回归斜率与稳定性"]

    I1 --> J["综合质量得分"]
    I2 --> J
    I3 --> J
    I4 --> J
    I5 --> J

    J --> K{"通过质量门槛"}
    K -->|否| L["失败原因归档<br/>返回候选生成"]
    K -->|是| M["进入标准化单因子回测"]

    classDef input fill:#eef4fa,stroke:#315b7d,color:#172b3a;
    classDef metric fill:#f5f7f9,stroke:#647581,color:#172b3a;
    classDef decision fill:#fff7e6,stroke:#8a6823,color:#3d321d;
    classDef output fill:#edf5ef,stroke:#427451,color:#17351f;

    class A,B,E,F,G,H,J input;
    class I1,I2,I3,I4,I5 metric;
    class C,K decision;
    class D,L,M output;
```

## 图5 标准化单因子回测

```mermaid
flowchart TB
    A["质量评价合格因子"] --> B["表达式规范化"]
    B --> C["在真实股票池计算因子值"]
    C --> D["横截面去极值与标准化"]
    D --> E["按照因子方向进行股票排序"]
    E --> F["选取Top-K股票"]
    F --> G["停牌、涨跌停与流动性检查"]
    G --> H["等权或约束权重分配"]
    H --> I["下一交易时点执行"]
    I --> J["扣除手续费与滑点"]
    J --> K["更新每日持仓与净值"]

    K --> L1["年化收益率"]
    K --> L2["Sharpe比率"]
    K --> L3["最大回撤"]
    K --> L4["Calmar比率"]
    K --> L5["换手率与交易成本"]

    L1 --> M["单因子回测报告"]
    L2 --> M
    L3 --> M
    L4 --> M
    L5 --> M

    classDef process fill:#eef4fa,stroke:#315b7d,color:#172b3a;
    classDef metric fill:#f5f7f9,stroke:#647581,color:#172b3a;
    classDef output fill:#edf5ef,stroke:#427451,color:#17351f;

    class A,B,C,D,E,F,G,H,I,J,K process;
    class L1,L2,L3,L4,L5 metric;
    class M output;
```

## 图6 因子筛选、去重与入库

```mermaid
flowchart LR
    A1["质量评价结果"] --> B["汇总候选因子证据"]
    A2["单因子回测结果"] --> B
    A3["表达式与运行元数据"] --> B

    B --> C["统一表达式格式"]
    C --> D["表达式哈希与完全重复检查"]
    D --> E{"是否重复"}
    E -->|是| F["保留表现更优版本"]
    E -->|否| G["进入绩效筛选"]
    F --> G

    G --> H{"样本外表现是否合格"}
    H -->|否| I["淘汰并登记拒绝原因"]
    H -->|是| J["稳定性与风险检查"]

    J --> K["因子标签<br/>动量、反转、量价、波动等"]
    K --> L["登记数据版本、股票池和预测周期"]
    L --> M["记录IC、收益、风险和覆盖率"]
    M --> N["形成版本化合格因子库"]

    classDef input fill:#eef4fa,stroke:#315b7d,color:#172b3a;
    classDef process fill:#e8f0f7,stroke:#315b7d,color:#172b3a;
    classDef decision fill:#fff7e6,stroke:#8a6823,color:#3d321d;
    classDef output fill:#edf5ef,stroke:#427451,color:#17351f;

    class A1,A2,A3 input;
    class B,C,D,F,G,J,K,L,M process;
    class E,H decision;
    class I,N output;
```

## 图7 市场状态识别与条件因子分析

```mermaid
flowchart TB
    A["全市场日频行情"] --> B["构造市场状态特征"]

    B --> B1["市场收益率"]
    B --> B2["市场波动率"]
    B --> B3["上涨股票比例"]
    B --> B4["横截面收益离散度"]
    B --> B5["成交活跃度"]

    B1 --> C["特征标准化与滚动估计"]
    B2 --> C
    B3 --> C
    B4 --> C
    B5 --> C

    C --> D["市场状态分类器"]
    D --> E1["牛市状态"]
    D --> E2["熊市状态"]
    D --> E3["震荡状态"]
    D --> E4["高波动状态"]

    E1 --> F["状态条件下的因子评价"]
    E2 --> F
    E3 --> F
    E4 --> F

    G["合格因子库"] --> F
    F --> H["计算条件IC、ICIR、收益与稳定性"]
    H --> I["构建市场状态—因子表现矩阵"]
    I --> J["识别各状态下的优势因子"]

    classDef input fill:#eef4fa,stroke:#315b7d,color:#172b3a;
    classDef feature fill:#f5f7f9,stroke:#647581,color:#172b3a;
    classDef state fill:#fff7e6,stroke:#8a6823,color:#3d321d;
    classDef output fill:#edf5ef,stroke:#427451,color:#17351f;

    class A,B,C,D,G input;
    class B1,B2,B3,B4,B5 feature;
    class E1,E2,E3,E4 state;
    class F,H,I,J output;
```

## 图8 动态因子选择与路由

```mermaid
flowchart LR
    A1["当前市场状态"] --> D["动态因子路由器"]
    A2["因子滚动绩效"] --> D
    A3["因子相关性矩阵"] --> D
    A4["因子风险与换手特征"] --> D
    A5["合格因子库"] --> D

    D --> E["计算状态条件因子得分"]
    E --> F["剔除高相关与信息重复因子"]
    F --> G["Top-K因子选择"]
    G --> H["Softmax或可学习权重分配"]

    H --> I1["因子1及动态权重"]
    H --> I2["因子2及动态权重"]
    H --> I3["因子K及动态权重"]

    I1 --> J["多因子加权合成"]
    I2 --> J
    I3 --> J

    J --> K["日期×股票综合Alpha矩阵"]

    classDef input fill:#eef4fa,stroke:#315b7d,color:#172b3a;
    classDef method fill:#e8f0f7,stroke:#315b7d,color:#172b3a;
    classDef selected fill:#fff7e6,stroke:#8a6823,color:#3d321d;
    classDef output fill:#edf5ef,stroke:#427451,color:#17351f;

    class A1,A2,A3,A4,A5 input;
    class D,E,F,G,H,J method;
    class I1,I2,I3 selected;
    class K output;
```

## 图9 Alpha合成与股票组合构建

```mermaid
flowchart TB
    A["动态选中的K个因子"] --> B["各因子横截面标准化"]
    C["动态因子权重"] --> D["加权Alpha合成"]
    B --> D

    D --> E["股票综合Alpha得分"]
    E --> F["股票横截面排序"]
    F --> G["选择Top-N股票"]

    G --> H1["停牌过滤"]
    G --> H2["涨跌停过滤"]
    G --> H3["流动性过滤"]
    G --> H4["可选行业与风险约束"]

    H1 --> I["可交易候选组合"]
    H2 --> I
    H3 --> I
    H4 --> I

    I --> J["组合权重优化"]
    J --> J1["等权配置"]
    J --> J2["单票权重上限"]
    J --> J3["风险预算或波动约束"]

    J1 --> K["目标持仓"]
    J2 --> K
    J3 --> K

    K --> L["与当前持仓比较"]
    L --> M["生成买入、卖出和调仓指令"]

    classDef input fill:#eef4fa,stroke:#315b7d,color:#172b3a;
    classDef process fill:#e8f0f7,stroke:#315b7d,color:#172b3a;
    classDef constraint fill:#fff7e6,stroke:#8a6823,color:#3d321d;
    classDef output fill:#edf5ef,stroke:#427451,color:#17351f;

    class A,C input;
    class B,D,E,F,G,I,J,L process;
    class H1,H2,H3,H4,J1,J2,J3 constraint;
    class K,M output;
```

## 图10 交易执行与绩效反馈

```mermaid
flowchart LR
    A["目标持仓"] --> B["生成调仓订单"]
    B --> C["下一交易时点执行"]

    C --> D1["成交价格"]
    C --> D2["手续费"]
    C --> D3["滑点"]
    C --> D4["涨跌停与停牌限制"]

    D1 --> E["更新实际持仓"]
    D2 --> E
    D3 --> E
    D4 --> E

    E --> F["计算每日组合收益"]
    F --> G["形成组合净值序列"]

    G --> H1["收益评价"]
    G --> H2["风险评价"]
    G --> H3["交易效率评价"]

    H1 --> I1["年化收益、超额收益"]
    H2 --> I2["波动率、Sharpe、最大回撤"]
    H3 --> I3["换手率、成本、成交率"]

    I1 --> J["组合绩效报告"]
    I2 --> J
    I3 --> J

    classDef input fill:#eef4fa,stroke:#315b7d,color:#172b3a;
    classDef process fill:#e8f0f7,stroke:#315b7d,color:#172b3a;
    classDef metric fill:#f5f7f9,stroke:#647581,color:#172b3a;
    classDef output fill:#edf5ef,stroke:#427451,color:#17351f;

    class A,B,C,E,F,G input;
    class D1,D2,D3,D4,H1,H2,H3 process;
    class I1,I2,I3 metric;
    class J output;
```

## 图11 强化学习奖励反馈闭环

```mermaid
flowchart TB
    A["环境状态<br/>市场状态、因子表现、当前持仓"] --> B["强化学习策略"]

    B --> C1["动作一：生成或选择因子"]
    B --> C2["动作二：分配因子权重"]
    B --> C3["动作三：调整组合持仓"]

    C1 --> D["因子评价与交易环境"]
    C2 --> D
    C3 --> D

    D --> E1["预测能力<br/>IC、Rank IC、ICIR"]
    D --> E2["收益能力<br/>组合收益、超额收益"]
    D --> E3["风险水平<br/>波动率、最大回撤"]
    D --> E4["交易代价<br/>换手率、手续费、滑点"]

    E1 --> F["复合奖励函数"]
    E2 --> F
    E3 --> F
    E4 --> F

    F --> G["优势估计"]
    G --> H["更新策略网络"]
    H --> B

    E1 --> I["当前已实现<br/>以单因子质量奖励为主"]
    E2 -.-> J["规划扩展<br/>完整组合收益奖励"]
    E3 -.-> J
    E4 -.-> J
    J -.-> F

    classDef state fill:#eef4fa,stroke:#315b7d,color:#172b3a;
    classDef action fill:#e8f0f7,stroke:#315b7d,color:#172b3a;
    classDef reward fill:#fff7e6,stroke:#8a6823,color:#3d321d;
    classDef output fill:#edf5ef,stroke:#427451,color:#17351f;

    class A,B,D,G,H state;
    class C1,C2,C3 action;
    class E1,E2,E3,E4,F reward;
    class I,J output;
```

## 图12 实验设计与学术验证框架

```mermaid
flowchart TB
    A["研究假设与评价问题"] --> B["时间序列样本划分"]

    B --> B1["训练集<br/>策略学习与参数估计"]
    B --> B2["验证集<br/>模型选择与门槛确定"]
    B --> B3["测试集<br/>最终样本外评价"]

    B1 --> C["候选方法"]
    B2 --> C
    C --> C1["PPO因子生成"]
    C --> C2["动态因子路由"]
    C --> C3["市场状态条件选择"]

    D["基线方法"] --> D1["随机因子生成"]
    D --> D2["固定因子组合"]
    D --> D3["无市场状态模型"]

    C1 --> E["统一实验协议"]
    C2 --> E
    C3 --> E
    D1 --> E
    D2 --> E
    D3 --> E

    E --> F1["预测能力比较"]
    E --> F2["收益与风险比较"]
    E --> F3["消融实验"]
    E --> F4["参数敏感性分析"]
    E --> F5["滚动窗口与跨时期稳健性"]
    E --> F6["统计显著性检验"]

    F1 --> G["样本外实证结果"]
    F2 --> G
    F3 --> G
    F4 --> G
    F5 --> G
    F6 --> G

    G --> H["研究结论、局限与适用边界"]

    classDef input fill:#eef4fa,stroke:#315b7d,color:#172b3a;
    classDef method fill:#e8f0f7,stroke:#315b7d,color:#172b3a;
    classDef baseline fill:#f5f7f9,stroke:#647581,color:#172b3a;
    classDef output fill:#edf5ef,stroke:#427451,color:#17351f;

    class A,B,B1,B2,B3 input;
    class C,C1,C2,C3,E,F1,F2,F3,F4,F5,F6 method;
    class D,D1,D2,D3 baseline;
    class G,H output;
```
