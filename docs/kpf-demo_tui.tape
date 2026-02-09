# kpf Demo — VHS Tape
# Run: vhs docs/kpf=demo_tui.tape

Output docs/kpf-demo_tui.gif

Set Shell zsh
Set Width 1900
Set Height 1300
Set WindowBar Colorful
# Set MarginFill "#0a1667"
# Set Margin 20
Set BorderRadius 14
Hide
Type "autoload -U colors && colors && clear"
Enter

# Set your prompt variable
Type 'PROMPT="%{$fg[yellow]%}(minikube)%{$reset_color%} %{$fg_bold[green]%}~/git/kpf%{$reset_color%} $ "'
Enter
# Schedule pod delete to trigger endpoint change and demonstrate auto-reconnect
Type "(sleep 8 && kubectl rollout restart deployment -n monitoring kube-prometheus-stack-grafana > /dev/null 2>&1) &"
Enter
Type "disown"
Enter
Type "clear"
Enter
Show

# ─── Scene: Interactive TUI Pod Selection ───
Type "kpf"
Enter
Sleep 1s
Down
Sleep 300ms
Down
Sleep 900ms
Enter
Sleep 900ms
Enter
Sleep 1900ms
Enter

# Wait for connection + pod delete + reconnect cycle
Sleep 15s

Screenshot docs/kpf-demo_tui.png
Sleep 100ms

# Clean exit
Ctrl+C
Sleep 3s
Type "clear"
Enter
Sleep 1s

Type "kpf --all --check --debug"
Enter
Sleep 3s
Screenshot docs/kpf-demo_check-all.png
Sleep 3s
Ctrl+C
Sleep 3s
