# Воспроизводимый прототип электросети GB

Прототип продолжает [учебный эксперимент в Colab](https://colab.research.google.com/drive/1NWfHJOzshvCLuPm2MDWf2O8AXp8plVQ0?usp=sharing).
Граф содержит связи, заданные исходными сетевыми таблицами, и подтверждённые
межсетевые коридоры. Принадлежность одному классу напряжения не создаёт ребро.

## Запуск в Windows

Из этой папки, Python 3.11 или новее:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe acquire.py --without-repd
.venv\Scripts\python.exe build_grid.py
.venv\Scripts\python.exe -m unittest -v test_grid.py
```

В `data/raw` включены Cardiff и два реестра NESO. Скрипт `acquire.py --without-repd`
проверяет их и получает DUKES. Для расширенной сборки скачайте также REPD:

```powershell
.venv\Scripts\python.exe acquire.py
```

Скрипт использует точные URL и сверяет SHA‑256 с манифестом. Существующие файлы
сохраняются. Для другого выпуска используйте локальный импорт и проверьте его
метаданные. Сборка и тесты после подготовки файлов выполняются офлайн.

Если сеть/портал недоступны, загрузите файлы вручную с указанных ниже страниц.
Локальный импорт поддерживается без сети:

```powershell
.venv\Scripts\python.exe build_grid.py --cardiff C:\Data\Data.xlsx --dukes C:\Data\DUKES_5.11.xlsx --repd C:\Data\REPD.csv --tec C:\Data\tec.csv --interconnector-register C:\Data\interconnectors.csv
```

Требуется исходная структура столбцов. Cardiff обязателен, остальные источники
опциональны: отсутствие файла оставляет соответствующий слой пустым.
Для произвольного локального выпуска проверьте дату/лицензию сами и используйте
отдельный manifest: скрипт не определяет год выгрузки по её имени.

## Источники и права

Точные скачанные версии и контрольные суммы: `data/raw/manifest.json`.
Полные метаданные Figshare и NESO сохранены рядом с файлами.

| Источник | Срез / смысл | Права и доступ |
|---|---|---|
| [Morteza Shafiekhani, GB Transmission Network Data, Cardiff](https://research-data.cardiff.ac.uk/articles/dataset/GB_Transmission_Network_Data/28152161), DOI 10.17035/cardiff.28152161 | Опубликован 14.02.2025; модель с нагрузкой зимнего пика 2024 | CC BY 4.0; XLSX; данные изменены при нормализации |
| [DESNZ DUKES 5.11](https://www.gov.uk/government/statistics/electricity-chapter-5-digest-of-united-kingdom-energy-statistics-dukes) | Станции major power producers, действовавшие на конец мая 2026; опубликован 30.07.2026 | OGL v3.0, кроме отдельно указанных прав; XLSX |
| [DESNZ REPD](https://www.gov.uk/government/publications/renewable-energy-planning-database-quarterly-extract) | Июль 2026; проекты всех статусов, не только действующие | OGL v3.0 с исключениями; CSV, исходная кодировка CP1252 |
| [NESO TEC](https://www.neso.energy/data-portal/transmission-entry-capacity-tec-register) | Снимок доступного реестра, дата файла/метаданных в manifest | NESO Open Data Licence; CSV / CKAN API |
| [NESO Interconnector Register](https://www.neso.energy/data-portal/interconnector-register) | Снимок 30.10.2026; контрактные права подключения, не паспорт кабеля | NESO Open Data Licence; CSV / CKAN API |

Contains public sector information licensed under the Open Government Licence v3.0.
Supported by National Energy SO Open Data. [Лицензия NESO](https://www.neso.energy/data-portal/neso-open-licence).
Граф, нормализованные таблицы и карта адаптированы из Morteza Shafiekhani (2025),
GB Transmission Network Data, Cardiff University, [версия 1](https://doi.org/10.17035/cardiff.28152161.v1),
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
Паспортные факты интерконнекторов сведены вручную из первичных страниц;
ссылки находятся в каждой строке `data/reference/interconnectors.csv`.
Карты и чертежи операторов не копируются и не выдаются за открытый GIS-набор.

## Что входит в модель

- GB — Англия, Шотландия и Уэльс. Иностранные узлы: только терминалы выбранных
  связей с FR, NL, BE, IE. Германия присутствует в сценарии строительства.
- Узел `substation_bus` — шина определённого напряжения из Cardiff. Название
  подстанции и название электростанции не считаются одним объектом.
- `ac_line` — явные пары `Terminal i/j` из листа Line. Если ссылка есть, но
  строки в Terminal нет, создаётся `unlocated_bus_reference`: имя известно,
  координаты и напряжение узла остаются пустыми. Опечатки не исправляются догадками.
- `transformer` — исходная запись Transformer. Она не содержит колонок концов.
  Разрешение допустимо только при точном совпадении имени с терминалом и наличии
  ровно одной шины каждого указанного HV/LV-напряжения в той же опубликованной
  координате. Это разрешение внутри модели, не проверка оперативной коммутации.
  Все неоднозначные записи сохраняются в audit без добавления ребра.
- `plant_connection` — проект NESO со статусом `Built` и `MW Connected > 0`, с уникальным
  совпадением нормализованного имени станции, совместимой технологией, отношением
  TEC к мощности в пределах 0.5–2 и отсутствием географического конфликта >50 км.
  Точка подключения сопоставляется с шиной по точному имени и напряжению.
  Эти ограничения отвергают ложные совпадения Coventry, Immingham, Spalding,
  Sutton Bridge. Это консервативное сопоставление реестров, требующее последующей
  ручной проверки идентичности, а не сертификат подключения конкретного агрегата.
- Строки Cardiff Static/Synchronous Generator сохранены отдельным модельным
  каталогом. В исходнике нет явной ссылки генератора на Terminal, поэтому
  совпадение имени записано как кандидат, но ребро не создаётся.
- `hvdc_interconnector` — агрегированный коридор между точками подключения к
  национальным сетям. Преобразователи, AC-подводы и кабель не разделены на
  фиктивные элементы без достаточных данных. МВт — номинал проекта;
  контрактные import/export МВт NESO хранятся отдельными полями.

Действующие: BritNed, Nemo, EWIC, Greenlink, IFA, IFA2, ElecLink.
NeuConnect — `under_construction`; отсутствует в `grid_active.*`.
Данные оператора ожидают ввод в 2028, даже если контрактная дата NESO иная.
У NESO точка NeuConnect — Wallend, в документах проекта — Grain West:
противоречие сохранено, узлы не объединены.
EWIC: Deeside не отождествляется с Connah's Quay, хотя так упрощён исходник
Cardiff. Для IFA2 используется документированный Chilling, а не исходный
эквивалент через Ninfield. Восемь иностранных эквивалентных линий Cardiff
исключены, чтобы не дублировать связи и не трактовать нулевые R/X как кабели.
Связи с Норвегией, Данией и Северной Ирландией находятся за границей этого прототипа.

## Файлы результата

- `exports/map.html` — интерактивная карта Folium/Leaflet. Прямые отрезки
  показывают связность, не реальные трассы. Узлы без координат не рисуются.
  Совпадающие координаты трансформаторов отображаются одной точкой с числом
  элементов. Связи без координат и NeuConnect перечислены в отдельной схеме.
  Для загрузки Leaflet и фоновых OSM-тайлов нужен интернет.
- `exports/endpoint_schematic.html` — автономная таблица-схема всех восьми
  коридоров, включая объекты без координат и строящийся NeuConnect.
- `exports/grid.json`, `grid.graphml` — полный `MultiGraph`, включая стройку.
- `exports/grid_active.json`, `grid_active.graphml` — семь действующих коридоров
  плюс историческая модель GB. «Active» исключает стройку, но не превращает
  Cardiff 2024/2025 в подтверждённую текущую сеть 2026 года.
- `exports/summary.json` — размеры, компоненты, типы и ограничения.
- `data/normalized/nodes.csv`, `edges.csv` — плоская машиночитаемая модель.
- `plant_inventory.csv` — DUKES + REPD. Реестры перекрываются: строки нельзя
  складывать для получения числа станций или общей мощности. Непривязанные
  станции не включены как фиктивные изолированные электрические узлы графа.
- `plant_connections_audit.csv`, `issues.json` — сопоставления, отказы, недостающие
  координаты и неоднозначные трансформаторы. Признаки `zero_impedance` и
  `terminal_voltage_mismatch` также входят в экспорт рёбер. Перед расчётом DC
  требуется разрешить эти случаи и проверить остальные параметры на физическую пригодность.
- `cardiff_*.csv`, `model_generators.csv` — исходные таблицы после удаления строки
  единиц измерения; сохранены номера строк Excel. `build_sources.json` связывает
  сборку с конкретными источниками и SHA256.

## Ограничения и следующий шаг

Это структурный прототип, не расчёт потокораспределения или надёжности.
Нет данных, позволяющих доказать происхождение импорта от конкретной зарубежной
станции. Иностранные генераторы не добавляются по географической близости.
Неизвестная длина остаётся пустой; нулевые длины Cardiff помечены в audit.
Нет вывода об экономической развитости севера/юга.

Для GB X/Y используется EPSG:27700 → WGS84 через pyproj; координаты REPD
считаются британской национальной сеткой. Северная Ирландия не преобразуется
этим правилом. Информация о расположении DUKES предоставлена генераторами и,
согласно примечаниям DESNZ, самим ведомством не проверена.

Следующий этап: сверить спорные названия, 83 неразрешённых трансформатора и
неполные шины с [NESO ETYS, Appendix A/B](https://www.neso.energy/research-publications/etys/documents),
подтвердить привязки станций и добавить реальные координаты Deeside/Great Island
по официальным GIS-источникам. Только после этого расширять зарубежную топологию.

<a id="simulation-inputs"></a>

## Входные данные для следующих этапов

Эти ряды и приложения придётся скачать для разработки симулятора. Для каждого
снимка запишите период, дату получения, формат, URL, лицензию и SHA‑256.

| Задача | Где и что скачать |
| --- | --- |
| Почасовая база GB | [NESO Historic Demand Data](https://www.neso.energy/data-portal/historic-demand-data) и [Historic Generation Mix](https://www.neso.energy/data-portal/historic-generation-mix). Скачать CSV за 2024 и 2025 или отфильтровать эти годы в общей выгрузке. Использовать дату и расчётный период, спрос, встроенные ветер и солнце, генерацию по топливу и обмен. Согласовать определение спроса с балансом. |
| Состав генерации и доступность | [DUKES, глава 5](https://www.gov.uk/government/statistics/electricity-chapter-5-digest-of-united-kingdom-energy-statistics-dukes), таблицы 5.8–5.9 и 5.11. Для наблюдаемой доступности выбрать в [Elexon API](https://bmrs.elexon.co.uk/api-documentation/endpoint) `/reference/bmunits/all` и `/datasets/MELS`. Для событий скачать [REMIT](https://bmrs.elexon.co.uk/api-documentation/endpoint/remit/list/by-event) с деталями по ID и учётом пересмотров. MEL и REMIT служат наблюдениями для оценки параметров, требуют сопоставления агрегатов и не дают полного журнала отказов. Применять [условия Elexon](https://www.elexon.co.uk/bsc/data/balancing-mechanism-reporting-agent/copyright-licence-bmrs-data/). |
| Сетевая модель | [NESO ETYS](https://www.neso.energy/research-publications/etys/documents), издание 2025, Appendix A и B. Скачать схемы и техническую книгу, сверить подключения, параметры и статус линий. Условия повторного распространения проверить в каждом приложении. |
