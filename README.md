# 澄桥检验档案汇交

澄桥检验中心白班接收仪器导出的有序读数，归档员把固定任务分卷移交，夜班凭完成单核对原值、换算值和卷位。Python 3.11 标准库即可运行。

```sh
python3 -B check_project.py
python3 -B -m unittest discover -s tests -t .
python3 -B demo.py
```

`check_project.py` 由控制台在物化项目时提供。演示在独立临时工作区加工 `samples/day_shift.json`，核对首卷短写、退卷、重开、续卷和固定单领取。

## 公开入口

先构造 `workspace.Workspace(root)`。构造和 `initialize()` 都会补齐存储结构，既有批、任务、介质记录、目录、退卷状态及完成单可继续使用。工作区对象在每次操作结束时释放 SQLite 连接，可以通过再次构造打开同一工作区。

| 模块及调用 | 结果 |
| --- | --- |
| `intake.batches.import_batch(ws, batch_id, multiplier, readings)` | 保存并返回 `BatchSnapshot`。非法输入或已登记批号抛出 `InvalidBatch`，整批无新增。`load_batch(ws, batch_id)` 按号读取，未知批返回 `None`。 |
| `transfer.jobs.freeze_job(ws, batch_id)` | 从已登记批冻结独立任务，返回 `JobManifest`，其中 `job_id` 为正整数。未知批抛出 `UnknownBatch`。 |
| `media.mount.mount(ws, volume_id, capacity)` | 返回 `VolumeRegistration`。挂载同一可写卷须使用原容量。非法卷号、非法容量、卷头冲突或已退卷抛出 `InvalidVolume`。 |
| `transfer.sender.ship(ws, job_id, volume_id)` | 从已确认原序送到当前可写卷，有待核尝试时先核原卷。返回 `ShippingProgress`，状态为 `partial`、`complete` 或 `unconfirmed`。满卷可确认零新增。 |
| `catalog.progress.progress(ws, job_id)` | 返回 `CatalogProgress`，包括 `total_rows`、`confirmed_count` 和按任务原序排列的 `locations`。未确认时计数为 `None`，卷位列表为空。 |
| `catalog.retirement.retire(ws, volume_id)` | 核实卷位后返回 `True` 并退卷。证据未核清返回 `False` 并维持原生命周期。已退卷重复调用返回 `True`。 |
| `audit.issue.issue(ws, job_id)` | 核齐后签发并返回 `Receipt`。部分或待核任务抛出 `IncompleteJob`，无新完成单。已签任务重复调用返回原单。 |
| `audit.receipts.get_receipt(ws, receipt_id)` | 从已签快照按号领取 `Receipt`。未知号返回 `None`。 |

`ship`、`progress` 和 `issue` 对未知任务抛出 `UnknownJob`。卷相关入口对未知或不可写的目标卷按上表拒绝。工作区或协调数据库无法打开时可能直接报告 I/O 或 SQLite 错误。`media.reader.read_mounted_rows` 可查已挂载卷的实际记录，卷不可在线核对时抛出 `EvidenceUnavailable`。

## 读数和卷位

批号为非空白字符串。读数输入为有序序列，元素是普通 Python 整数或 `None`，倍率也是普通 Python 整数。空序列可以形成零行任务。有效读数乘该批固定倍率，合计仅累加有效换算值。读数、倍率和合计以带符号的十六进制文本保存，转回 Python 整数计算。任务原序从零开始，同值的不同原行以及缺测原行各占一个卷位。

卷号使用 1 至 64 个 ASCII 字母、数字、下划线或连字符，以字母或数字起头。总容量为 0 至 SQLite 最大有符号整数之间的整数。物理槽位从零开始；同一槽号可出现在不同卷。完成单保存任务号、批号、行数、换算合计，以及每行的原序、原值、换算值、卷号和槽位。

## 正常换卷

中心先提交待核尝试。每卷使用独立的 SQLite 载体，写入介质后中心再提交实际卷位和尝试结清。回包丢失后可按任务查真实前缀。若介质提交而中心确认失败，重办会先在原挂载卷查本次实际记录。卷上的待核尝试皆已结清且逐行对账一致时，才能正常退卷。旧卷退下后仍可从中心目录查旧卷位，已签完成单可按原号领取。
