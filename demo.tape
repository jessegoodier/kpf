Output demo.gif

Set Shell bash
Set FontSize 16
Set Width 900
Set Height 500
Set Padding 10
Set Framerate 30
Set TypingSpeed 40ms
Set Theme "Catppuccin Mocha"

# Clean prompt and PATH setup (hidden from viewer)
Hide
Type "export PS1='$ '"
Enter
# Schedule pod delete to trigger endpoint change and demonstrate auto-reconnect
Type "(sleep 8 && kubectl delete pod -n monitoring prometheus-kube-prometheus-stack-prometheus-0 --grace-period=1 > /dev/null 2>&1) &"
Enter
Type "disown"
Enter
Type "clear"
Enter
Sleep 500ms
Show

# Start kpf port-forward to prometheus
Type "kpf svc/kube-prometheus-stack-prometheus 9090:9090 -n monitoring"
Sleep 500ms
Enter

# Wait for connection + pod delete + reconnect cycle
Sleep 32s

# Clean exit
Ctrl+C
Sleep 2s
