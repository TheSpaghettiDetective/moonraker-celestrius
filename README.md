# Celestrius Data Collection for Klipper

## Install and setup Celestrius data collection program

```
cd && git clone https://github.com/TheSpaghettiDetective/moonraker-celestrius.git
cd moonraker-celestrius
./celestrius.sh install
```


##  Enable Celestrius data collection (disabled by default)

```
cd ~/moonraker-celestrius
./celestrius.sh enable
```

## Disable Celestrius data collection

```
cd ~/moonraker-celestrius
./celestrius.sh disable
```

## Re-install and re-setup

```
cd ~/moonraker-celestrius
./celestrius.sh install
```

## Update to the latest version

```
cd ~/moonraker-celestrius
git pull
sudo systemctl restart moonraker-celestrius
```

## Display uninstall instructions

```
cd ~/moonraker-celestrius
./celestrius.sh uninstall
```
