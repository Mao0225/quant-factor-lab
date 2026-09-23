"""Render completed preregistered evidence; never train or execute backtests."""
import argparse
import math
from datetime import datetime, timezone
from pathlib import Path

from closed_loop_research.protocol import Protocol
from closed_loop_research.storage import digest, read_json


EXPECTED = {'fixed3', 'fixed12', 'random7', 'ppo7', 'random19', 'ppo19'}
LABELS = {
    'return_20': '20日收益', 'return_60': '60日收益',
    'neg(return_1)': '1日反转', 'neg(return_5)': '5日反转',
    'neg(volatility_20)': '20日低波动', 'neg(volatility_60)': '60日低波动',
    'volume_ratio_5': '5日相对成交量', 'volume_ratio_20': '20日相对成交量',
    'neg(ma_gap_5)': '负5日均线偏离', 'neg(ma_gap_20)': '负20日均线偏离',
    'neg(range_relative)': '低相对振幅', 'neg(intraday_return)': '日内反转',
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def active(weights):
    return {k: float(v) for k, v in weights.items() if abs(float(v)) > 1e-12}


def number(value, percent=False):
    value = float(value)
    require(math.isfinite(value), 'Nonfinite metric in completed evidence')
    return f'{value:.2%}' if percent else f'{value:.6f}'


def link(path):
    return f'[{path.name}](<{path.resolve().as_posix()}>)'


def scoring_parity_section(study):
    """Summarize optional, already-written F/E parity evidence without computing."""
    lines = ['', '## 研究/选股评分交接核验', '',
             '这里分别报告原严格数值核验、排序核验和额外误差诊断。严格失败保留原样；排序一致或误差较小不等于严格核验通过，也不自动决定模型是否开放使用。']
    samples = []
    for key, filename in [('固定十二因子', 'fixed12_scoring_parity.json'),
                          ('随机搜索7', 'random7_scoring_parity.json')]:
        path = study / filename
        if not path.is_file():
            lines += ['', f'{key}：尚无已写出的抽样评分核验文件。']
            continue
        data = read_json(path)
        checks = [check for case in data['cases'] for check in case['checks']]
        require(bool(checks), f'{filename}: empty parity checks')
        errors = [value for check in checks for value in check['max_absolute_errors'].values()]
        samples.append((key, path, data, checks, max(errors)))
    if samples:
        lines += ['', '| 模型 | 抽样检查数 | 检查通过/失败 | 严格数值失败数 | 原报告总体通过 | 最大绝对误差 | 全排序均一致 |',
                  '|---|---:|---:|---:|---|---:|---|']
        for key, path, data, checks, maximum in samples:
            passed = sum(bool(check['passed']) for check in checks)
            numerical_failures = sum(not check['numeric_equal'] for check in checks)
            lines.append(f'| {key} | {len(checks)} | {passed}/{len(checks)-passed} | '
                         f'{numerical_failures} | {data["passed"]} | {maximum:.6e} | '
                         f'{all(check["complete_eligible_ranking_equal"] for check in checks)} |')
        lines += ['', '抽样检查总数包含登记起点、历史窗口诊断及实际冻结模型等不同用例，不应把诊断用例都算作实际模型证据。']
        for key, path, data, checks, maximum in samples:
            tolerance = data['tolerance']
            lines += ['', f'{key}原严格阈值：rtol={tolerance["rtol"]:g}、atol={tolerance["atol"]:g}。'
                      f'原始结果见 {link(path)}。']
            if not data['passed']:
                lines += ['', f'**{key}原严格核验失败，未被后续误差诊断改写为通过。**']
    daily_path = study / 'random7_all_dates_parity.json'
    if daily_path.is_file():
        daily = read_json(daily_path)
        require(daily['days_checked'] == len(daily['days']), 'Daily parity date count mismatch')
        lines += ['', '随机搜索7的全F/E日期复核：', '',
                  '| 实测日期数 | 严格数值失败日期数 | 最大绝对误差 | 全日期完整排序一致 | 全日期Top50一致 | 额外绝对误差诊断值 | 诊断界限及对齐/缺失检查均满足 |',
                  '|---:|---:|---:|---|---|---:|---|',
                  f'| {daily["days_checked"]} | {daily["strict_failed_days"]} | '
                  f'{daily["max_absolute_error"]:.6e} | {daily["exact_ranking_all_days"]} | '
                  f'{daily["top50_all_days"]} | {daily["diagnostic_absolute_bound"]:g} | '
                  f'{daily["diagnostic_bound_met"]} |', '',
                  f'原严格阈值仍为 {daily["strict_tolerance"]:g}；额外'
                  f' {daily["diagnostic_absolute_bound"]:g} 仅用于独立的实测误差诊断，'
                  '没有更改内核、冻结评分器或原严格阈值，也不构成对未来日期误差的保证。'
                  f'逐日证据：{link(daily_path)}。']
    else:
        lines += ['', '随机搜索7尚无已写出的全F/E日期核验报告，不能由抽样检查推断所有日期一致。']
    diagnosis_path = study / 'random7_numerical_diagnosis.md'
    if diagnosis_path.is_file():
        diagnosis = diagnosis_path.read_text(encoding='utf-8')
        require(bool(diagnosis.strip()), 'Empty numerical diagnosis document')
        lines += ['', f'独立数值定位说明：{link(diagnosis_path)}。'
                  '该文档与全日期报告属于诊断证据，不能用来抹除原严格失败；模型可用性决定应另行记录。']
    return lines


def report(study, output):
    study, output = Path(study).resolve(), Path(output).resolve()
    results_path = study / 'results.json'
    if not results_path.is_file():
        raise FileNotFoundError(f'结果尚未齐备：{results_path} 不存在；报告没有读取任何组的V/T结果，也不会等待或启动计算。')
    registration = read_json(study / 'registration.json')
    results = read_json(results_path)
    registered = registration['rows']
    require(len(registered) == 6 and {r['key'] for r in registered} == EXPECTED,
            'Registration must contain the six intended arms exactly once')
    require(len(results['rows']) == 6 and {r['key'] for r in results['rows']} == EXPECTED,
            'Results must contain all six registered arms exactly once')
    require(results['project_id'] == registration['project_id'], 'Project mismatch')
    result_by_key = {r['key']: r for r in results['rows']}
    system = study.parent.parent
    ready = []
    # Check completion of every arm before opening any selection/test evidence.
    for row in registered:
        result = result_by_key[row['key']]
        require(row['experiment_id'] == result['experiment_id'], 'Experiment mismatch')
        experiment_id = row['experiment_id']
        require(experiment_id.isalnum(), 'Invalid experiment id')
        run = system / 'experiments' / experiment_id / 'run'
        status = read_json(run / 'status.json')
        protocol = Protocol.from_dict(read_json(run / 'protocol.json'))
        require(status['phase'] == 'finished' and status['batch'] == protocol.batches,
                f'{row["key"]}: training is not finished')
        require(protocol.digest == row['protocol_digest'] == Protocol.from_dict(row['protocol']).digest,
                f'{row["key"]}: protocol digest mismatch')
        for name in ('frozen_model.json', 'selection.json', 'test_result.json'):
            require((run / name).is_file(), f'{row["key"]}: missing completed {name}')
        ready.append((row, result, run, protocol, status))
    evidence = []
    for row, result, run, protocol, status in ready:
        frozen = read_json(run / 'frozen_model.json')
        selection = read_json(run / 'selection.json')
        test = read_json(run / 'test_result.json')
        require(digest({k: v for k, v in frozen.items() if k != 'model_id'}) == frozen['model_id'],
                f'{row["key"]}: frozen model identity mismatch')
        require(frozen['model_id'] == selection['frozen_model_id'] == test['frozen_model_id'],
                f'{row["key"]}: selection/test provenance mismatch')
        require(frozen['protocol_digest'] == protocol.digest, 'Frozen protocol mismatch')
        require(active(frozen['weights']) == active(result['weights']), 'Results weights mismatch')
        batches = [read_json(path) for path in sorted((run / 'batches').glob('*-committed.json'))]
        require(len(batches) == protocol.batches, 'Missing committed batches')
        require([b['batch_id'] for b in batches] == list(range(1, protocol.batches + 1)),
                'Non-contiguous committed batch sequence')
        trials = [trial for batch in batches for trial in batch['trials']]
        changes = sum(bool(batch['decision']['changed']) for batch in batches)
        require(changes == status['pool_version'], 'Pool version/change count mismatch')
        require(active(batches[-1]['decision']['chosen']['weights']) == active(status['pool']),
                'Latest committed pool mismatch')
        positive = sum(t['reward'] > 0 for t in trials)
        negative = sum(t['reward'] < 0 for t in trials)
        quality_failures = sum(t['status'] == 'quality_failure' for t in trials)
        used = sum(bool(t.get('candidate_used')) for t in trials)
        require(len(trials) == result['trials'] and positive == result['positive_rewards']
                and negative == result['negative_rewards'] and used == result['candidates_used']
                and quality_failures == result['quality_failures'], 'Candidate summary mismatch')
        budget = status['budget']
        actual = int(budget['actual_f']) + int(budget['actual_e']) + int(selection['actual_calls']) + int(test['actual_calls'])
        evidence.append(dict(row=row, result=result, run=run, protocol=protocol, status=status,
                             frozen=frozen, selection=selection, test=test, trials=trials, batches=batches,
                             changes=changes, positive=positive, negative=negative, used=used,
                             quality_failures=quality_failures, actual=actual))
    correlation = read_json(study / 'factor_correlation_audit.json')
    require(correlation['protocol_digest'] == next(x[3].digest for x in ready if x[0]['key'] == 'fixed12'),
            'Correlation audit protocol mismatch')
    require(all(a['segment'] == 'F' and a['allowed'] for a in correlation['data_access_audit']),
            'Correlation audit must be F only')
    handoff = read_json(study / 'handoff_plan.json')
    chosen_keys = handoff['chosen_keys']
    require(len(chosen_keys) == len(set(chosen_keys)) and set(chosen_keys).issubset(EXPECTED),
            'Invalid handoff plan keys')
    registered_names = {row['key']: row['name'] for row in registered}
    lines = ['# 十二因子组合探索 v1：完整实验报告', '',
             f'生成时间：{datetime.now(timezone.utc).isoformat()}。项目：`{registration["project_id"]}`。', '',
             '本报告读取已完成的六组实验及其冻结、提交和历史测试记录，没有重新训练、计算评分或运行回测。全部预登记组均列出，不按收益筛掉失败或相同组合。', '',
             '## 这轮具体做了什么', '',
             '十二因子是人工预先设计的等权起点，每项初始权重1/12，覆盖收益、反转、波动、量比、均线偏离和振幅。它不是PPO自动发现的十二条独立规律。固定三因子是原组合参照，固定十二因子用于观察换起点的影响；随机和PPO从同一个十二因子起点出发，在相同候选和组合搜索预算下比较。', '',
             '每个随机/PPO实验计划4轮×6个候选，组合搜索每次最多12次F评估，容量上限16个有效因子。允许因子退出，最终数量以冻结模型实际非零权重为准。随机种子控制候选抽样和搜索随机性；7与19是两次不同随机路径，不是年份或模型评级。', '',
             'F用于拟合组合权重；E用于反馈奖励及接受组合更新；V仅从预登记批次里选择冻结组合；所有组冻结后再做T历史测试。V选中的组合可能来自较早批次，因此冻结因子数与最新池因子数可以不同。', '',
             '本轮优化组使用0.05、0.025、0.01三个登记尺度；重启门槛为8×3=24次停滞，Q=12内达不到。这是以0.05为主的局部搜索，不能称为已进行充分的多尺度重启优化。', '',
             '## 六组结果', '',
             '| 实验 | 冻结因子数 | 最新池数 | 池变更数 | 候选数 | 正/零/负奖励 | V目标 | T累计收益 | T最大回撤 | 实际回测计算数 |',
             '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for e in evidence:
        n = len(e['trials']); t = e['test']['metrics']
        lines.append(f'| {e["row"]["name"]} | {len(active(e["frozen"]["weights"]))} | '
                     f'{len(active(e["status"]["pool"]))} | {e["changes"]} | {n} | '
                     f'{e["positive"]}/{n-e["positive"]-e["negative"]}/{e["negative"]} | '
                     f'{number(e["frozen"]["selection_objective"])} | {number(t["total_return"], True)} | '
                     f'{number(t["max_drawdown"], True)} | {e["actual"]} |')
    unique = len({digest(active(e['frozen']['weights'])) for e in evidence})
    lines += ['', f'六组冻结模型共有 **{unique} 种不同的精确公式—权重组合**。这是实测身份比较，不代表这些组合的股票排序、风险或信息来源相互独立。', '',
              'V目标为年化净对数日收益均值扣除方差风险惩罚，即 annual_days×[mean(log(1+r))−risk_lambda×var(log(1+r))/2]，不是收益百分比；T累计收益、最大回撤以记录原值显示，回撤通常为负。正奖励含义服从登记奖励定义；质量失败的−1奖励计入负数。实际计算数为F、E、V、T实际回测调用之和，不把缓存命中当成新计算。', '',
              '| 实验 | F实际 | E实际 | V实际 | T实际 | 质量失败 | F搜索使用候选次数 | PPO更新数 |',
              '|---|---:|---:|---:|---:|---:|---:|---:|']
    for e in evidence:
        b = e['status']['budget']
        lines.append(f'| {e["row"]["name"]} | {b["actual_f"]} | {b["actual_e"]} | '
                     f'{e["selection"]["actual_calls"]} | {e["test"]["actual_calls"]} | '
                     f'{e["quality_failures"]} | {e["used"]} | {e["status"]["ppo_updates"]} |')
    lines += ['', '“F搜索使用候选”只说明临时组合给该候选非零权重，不等于E段正式接纳；池变更数同时包括旧因子重新调权，不能全部解释为发现新因子。', '',
              '## 每组冻结公式和真实权重', '',
              '以下只列非零权重。权重绝对值和为1；负权重表示因子贡献方向相反，不直接代表卖空该股票。最终股票组合仍按系统登记的选股及交易规则执行。']
    for e in evidence:
        frozen = e['frozen']; initial = set(e['protocol'].initial_expressions)
        frozen_weights = active(frozen['weights'])
        tiny_count = sum(abs(weight) < 0.01 for weight in frozen_weights.values())
        lines += ['', f'### {e["row"]["name"]}', '',
                  f'实验ID：`{e["row"]["experiment_id"]}`；模型版本：`{e["result"]["model_version"]}`。'
                  f'冻结选自第{frozen["selected_batch"]}轮、池版本{frozen["pool_version"]}；最新池版本{e["status"]["pool_version"]}。', '',
                  f'非零权重公式共 **{len(frozen_weights)}项**，其中绝对权重 **小于1%的有{tiny_count}项**。'
                  '非零采用内核阈值绝对值>1e-12；微小权重只表示仍参与计算，不应当据数量称其为强参与。', '',
                  '| 公式 | 中文含义 / 来源 | 非零权重 |', '|---|---|---:|']
        for expression, weight in sorted(frozen_weights.items(), key=lambda x: -abs(x[1])):
            description = LABELS.get(expression, '生成公式；含义以公式为准')
            origin = '人工登记起点' if expression in initial else '研究候选'
            lines.append(f'| `{expression}` | {description}；{origin} | {weight:.9f} |')
        lines += ['', f'原始证据：{link(e["run"] / "frozen_model.json")}、'
                  f'{link(e["run"] / "selection.json")}、{link(e["run"] / "test_result.json")}。']
    lines += scoring_parity_section(study)
    m = correlation['metrics']
    lines += ['', '## 十二个公式是否代表十二份独立信息', '',
              f'独立审计仅使用F的{correlation["included_dates"]}个信号日，日期为'
              f'{correlation["signal_bounds"][0]}至{correlation["signal_bounds"][1]}，'
              f'每日共同有效股票{correlation["complete_observations_min"]}–{correlation["complete_observations_max"]}只。', '',
              '先按内核规则对每个因子做每日横截面标准化，再在十二项均有效的共同股票上计算Pearson相关，最后对每日相关矩阵等权平均。参与率有效维度=(Σλ)²/Σλ²；熵有效秩=exp(−Σp·ln p)，p为特征值占比。', '',
              f'参与率有效维度 **{m["participation_ratio"]:.3f}**，熵有效秩 **{m["entropy_effective_rank"]:.3f}**；'
              f'前3主成分解释 **{m["top_three_share"]:.2%}**，90%/95%需要'
              f' **{m["components_for_90_percent"]}/{m["components_for_95_percent"]}** 个主成分。', '',
              '| 高相关公式对 | 平均每日相关 |', '|---|---:|']
    for pair in correlation['pairs'][:5]:
        lines.append(f'| `{pair["factor_a"]}` / `{pair["factor_b"]}` | {pair["mean_daily_pearson"]:.3f} |')
    handoff_names = '、'.join(f'**{registered_names[key]}**（`{key}`）' for key in chosen_keys)
    lines += ['', '12个公式不等于12个独立信息源。上述维度只描述F样本内输入相关性的集中程度，不是独立经济来源的精确数量，也不衡量预测收益。该审计未用于替换因子或修改已登记协议。', '',
              '## 模型交接依据', '',
              f'交接计划指定：{handoff_names}。计划文件记录于T尚未运行时，选择依据是人工设计的十二因子固定基准，加上首个已完成冻结、冻结公式数超过10的搜索组；不是按照T收益排名挑选。随机搜索组应明确标为随机搜索模型，不得称为PPO发现。', '',
              f'登记原文：{handoff["basis"]}', '',
              f'其余组处理：{handoff["remaining_arms"]} 全部预登记随机/PPO组仍完整报告，不因交接选择而删除其他结果。', '',
              '## 结论的适用范围', '',
              '本轮能说明真实多因子起点、组合优化、反馈训练、冻结交接和历史测试是否发生，以及相同预算下各随机路径得到什么结果。只有两个种子、每个生成组24条候选、4轮更新，不能证明PPO稳定优于随机搜索；单个模型收益更高或因子更多也不能作为证明。', '',
              'T已被此前研究观察过，属于历史诊断，不是全新留出集。500股是固定样本，存在样本选择偏差；原始价格复权及公司行动未完全核验，停牌/开盘交易可行性采用原型假设，未覆盖完整涨跌停、流动性和退市结算。未经时点核验的财务字段未进入这些价量训练公式。收益和回撤仅适用于这些数据与执行假设。', '',
              '本轮不会为了得到超过10个因子而拒绝缩减；固定十二因子满足“实际运行十二因子组合”的演示，但人工构造起点本身不等于新增研究发现。优化组是否真正改变以及最后保留多少公式，应以上表和冻结权重为准。', '',
              '## 可复核材料', '',
              f'- 登记协议：{link(study / "registration.json")}。',
              f'- 六组结果：{link(results_path)}。',
              f'- 交接选择登记：{link(study / "handoff_plan.json")}。',
              f'- F相关审计：{link(study / "factor_correlation_audit.json")}。',
              f'- 旧三因子不变原因：{link(study / "old_three_factor_diagnosis.md")}。', '',
              '复现本报告：`python -m closed_loop_research.scripts.report_diverse12_exploration`。脚本先要求六组结果及完成证据齐备，然后读取已有记录；缺结果会报错退出，不等待、不启动实验，也不改写源记录。']
    acceptance = []
    if (study / 'evidence_audit.json').exists():
        audit = read_json(study / 'evidence_audit.json')
        acceptance += ['## 实验记录独立核验', '',
                       f'记录核验通过：**{audit["passed"]}**。核对{audit["totals"]["artifacts_verified"]}个已有回测工件、'
                       f'重算{audit["totals"]["rewards_recomputed"]}条已完成候选奖励；'
                       f'{audit["totals"]["pool_changes"]}次池更新、{audit["totals"]["ppo_updates"]}次PPO更新有对应证据。'
                       '这验证实验记录与执行过程，不代表收益有效或所有模型都通过选股评分验收。', '',
                       f'完整证据：{link(study / "evidence_audit.json")}。', '']
    if (study / 'handoff_result.json').exists():
        delivered = read_json(study / 'handoff_result.json')
        acceptance += ['## 实际交付状态', '']
        for item in delivered['models']:
            acceptance.append(f'- **{item["name"]}**：{item["status"]}。{item["reason"]}')
        acceptance += ['', f'可用性和选股结果记录：{link(study / "handoff_result.json")}。', '']
    position = lines.index('## 结论的适用范围')
    lines[position:position] = acceptance
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--study', default='closed_loop_research/workspace/system_v1/studies/twelve_factor_v1')
    parser.add_argument('--output', default='closed_loop_research/docs/十二因子组合探索_v1.md')
    args = parser.parse_args()
    try:
        print(report(args.study, args.output))
    except (FileNotFoundError, ValueError, KeyError) as exc:
        parser.exit(1, f'报告未生成：{exc}\n')
