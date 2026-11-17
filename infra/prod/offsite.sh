#!/bin/sh
# Runs in the `offsite` container: mirror backups and uploaded files to GCS every minute.
# No --delete-unmatched-destination-objects: objects removed locally stay in GCS until the
# bucket lifecycle rule expires them (30 days), so a local mistake cannot erase backups.
while true; do
  gcloud storage rsync --recursive /archive "gs://$BACKUP_BUCKET/archive" || echo "archive sync FAILED"
  gcloud storage rsync --recursive /data/storage "gs://$BACKUP_BUCKET/storage" || echo "storage sync FAILED"
  sleep 60
done
