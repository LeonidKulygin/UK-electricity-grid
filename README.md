# Анализ электрической сети Великобритании с помощью графов

[ПРОЕКТ](https://colab.research.google.com/drive/1NWfHJOzshvCLuPm2MDWf2O8AXp8plVQ0?usp=sharing)


https://colab.research.google.com/drive/1NWfHJOzshvCLuPm2MDWf2O8AXp8plVQ0?usp=sharing

## Описание проекта
Этот проект посвящен анализу данных об электрической сети Великобритании, включая исследование распределения напряжения и кластеризацию данных для выявления закономерностей. Проект реализован в Jupyter Notebook с использованием Python и библиотек для анализа данных и визуализации.

## Цели проекта
1. **Загрузка и предварительная обработка данных**:
   - Импорт данных из CSV-файла.
   - Переименование столбцов для удобства работы.
   - Исследование статистических характеристик напряжения.
   - **Визуализация результата в графовом представлении на реальной карте**
     
2. **Визуализация данных**:
   - Построение гистограммы распределения напряжения.
   - Использование библиотек `matplotlib` и `seaborn` для наглядного представления данных.

3. **Кластеризация данных**:
   - Применение алгоритма Gaussian Mixture Model (GMM) для кластеризации данных по напряжению.
   - Визуализация результатов кластеризации с помощью scatter plot.

## Используемые технологии и библиотеки
- **Python**: Основной язык программирования для анализа данных.
- **Pandas**: Для работы с данными в табличной форме.
- **Matplotlib/Seaborn**: Для визуализации данных.
- **Scikit-learn**: Для реализации алгоритма кластеризации (Gaussian Mixture Model).
- **Jupyter Notebook**: Интерактивная среда для выполнения кода и визуализации результатов.

## Результаты
- Проведена загрузка и предварительная обработка данных.
- Построена гистограмма распределения напряжения, что позволило наглядно увидеть основные тенденции в данных.
- Реализована кластеризация данных с помощью GMM, что помогло выделить группы объектов с похожими характеристиками напряжения.
- Результаты кластеризации визуализированы, что упростило интерпретацию данных.
- С помощью графового представления было выявлено, что Юг Великобритании более развит, чем север. 
