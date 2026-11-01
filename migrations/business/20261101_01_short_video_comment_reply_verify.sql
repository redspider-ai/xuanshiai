-- 20261101_01_short_video_comment_reply (verify)
-- 期望：admin_reply 列存在且类型为 varchar(500)、可空。
SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'short_video_comment'
  AND COLUMN_NAME = 'admin_reply';
