-- 为药品表增加明确类别。只给本项目内置的 10 个演示药品回填类别；
-- 其他药品保持 NULL，避免把“治疗领域”错误当成药品类别。
SET @has_drug_class = (
    SELECT COUNT(*)
    FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = 'drugs'
      AND column_name = 'drug_class'
);
SET @migration_sql = IF(
    @has_drug_class = 0,
    'ALTER TABLE drugs ADD COLUMN drug_class VARCHAR(20) NULL COMMENT ''明确药品类别：抗生素/非抗生素；未分类时为 NULL'' AFTER therapeutic_area',
    'SELECT 1'
);
PREPARE migration_stmt FROM @migration_sql;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

UPDATE drugs
SET drug_class = CASE
    WHEN generic_name IN ('阿莫西林胶囊', '注射用头孢曲松钠') THEN '抗生素'
    WHEN generic_name IN (
        '布洛芬缓释胶囊', '盐酸二甲双胍片', '阿托伐他汀钙片',
        '磷酸奥司他韦胶囊', '蒙脱石散', '硝苯地平控释片',
        '阿司匹林肠溶片', '连花清瘟胶囊'
    ) THEN '非抗生素'
    ELSE NULL
END
WHERE drug_class IS NULL;
