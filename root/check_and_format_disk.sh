#!/bin/sh
set -x
# 日志文件路径
LOG_FILE="/var/log/check_and_format_disk.log"

# 将所有输出重定向到日志文件
exec > >(tee -a $LOG_FILE) 2>&1

# 检查是否存在未格式化的硬盘
unformatted_disks=()
check_unformatted_disk() {
    unformatted_disks=()
    for disk in $(lsblk -dn -o NAME); do
        if [ -z "$(lsblk -no FSTYPE /dev/$disk)" ]; then
            unformatted_disks+=("/dev/$disk")
        fi
    done
    
    if [ ${#unformatted_disks[@]} -eq 0 ]; then
        echo "没有找到未格式化的磁盘"
        return 1
    fi
    
}

# 格式化硬盘
format_disk() {
    local disk=$1
    echo "Formatting $disk..."
    mkfs.ext4 "$disk"
}

# mount硬盘
mount_disk() {
    local disk=$1
    local mount_point=$2
    echo "Mounting $disk to $mount_point..."
    mkdir -p $mount_point
    mount "$disk" $mount_point -t ext4
}
# rsync src source_dir dest end_disk
rsync_data() {
    local src=$1
    local dest=$2
    mount_disk $dest /temp
    rsync -av "${src}/" /temp
}

# write fstab
write_config_fstab() {
    local disk=$1
    local mount_point=$2
    echo "Writing to /etc/config/fstab..."
    local uuid=$(blkid -s UUID -o value ${disk})
    echo >> /etc/config/fstab
    echo "config 'mount'" >> /etc/config/fstab
    echo -e "\toption\ttarget\t'$mount_point'" >> /etc/config/fstab
    echo -e "\toption\tuuid\t'$uuid'" >> /etc/config/fstab
    echo -e "\toption\tenabled\t'0'" >> /etc/config/fstab
}


main() {
    check_unformatted_disk
    i=0
    for disk in ${unformatted_disks[*]}; do
        echo "发现未格式化的硬盘: $disk"
        if [ $i -eq 0 ]; then
            echo "开始格式化硬盘..."
            format_disk $disk
            rsync_data /mnt $disk
            write_config_fstab $disk /mnt
        elif [ $i -eq 1 ]; then
            break
        fi
        i=$((i+1))

    done
}

main

set +x
