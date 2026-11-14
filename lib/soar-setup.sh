
useradd -r -M -s /bin/false -c "vaydns service user" -d /nonexistent vaydns
firewall-cmd --permanent --add-forward-port=port=53:proto=udp:toport=5300
firewall-cmd --reload

mkdir /etc/soar
cp soar-server /usr/local/bin/
chmod +x /usr/local/bin/soar-server
semanage fcontext -a -t bin_t "/usr/local/bin/soar-server"
restorecon -v /usr/local/bin/soar-server

/usr/local/bin/soar-server keygen | awk '
  $1 == "private" { print $2 > "server.key" }
  $1 == "public"  { print $2 > "server.pub" }
'

cp server.key server.pub /etc/soar/
chown vaydns:vaydns /etc/soar/*
cp soar-server.service /etc/systemd/system
systemctl enable soar-server.service
systemctl start soar-server.service
systemctl status soar-server.service
