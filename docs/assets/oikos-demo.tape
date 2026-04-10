# oikos-demo.tape
# Recording script for Charm VHS tool (or OBS manual guide)
# Captures: boot sequence → oikos info → oikos room list

Output docs/assets/oikos-boot.gif

Set Shell "powershell"
Set FontFamily "IBM Plex Mono"
Set FontSize 16
Set Width 1200
Set Height 700
Set Theme { "name": "oikOS", "black": "#0D0D0D", "red": "#FF4500", "green": "#D4A017", "yellow": "#FFB000", "blue": "#8B6914", "magenta": "#D4A017", "cyan": "#D4A017", "white": "#E0E0E0", "brightBlack": "#453510", "brightRed": "#FF4500", "brightGreen": "#FFB000", "brightYellow": "#FFB000", "brightBlue": "#D4A017", "brightMagenta": "#FFB000", "brightCyan": "#FFB000", "brightWhite": "#FFFFFF", "background": "#0D0D0D", "foreground": "#D4A017", "selectionBackground": "#D4A017", "cursorColor": "#D4A017" }

Type "oikos serve"
Enter
Sleep 8s

Type "oikos info"
Enter
Sleep 3s

Type "oikos room list"
Enter
Sleep 3s
