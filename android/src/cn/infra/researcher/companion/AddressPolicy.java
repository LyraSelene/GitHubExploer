package cn.infra.researcher.companion;
import java.net.URI;

final class AddressPolicy {
    static URI parse(String value) throws Exception {
        String raw=value.trim(); if(!raw.startsWith("http://"))raw="http://"+raw;
        URI u=new URI(raw); String host=u.getHost();
        if(!"http".equals(u.getScheme())||host==null||u.getUserInfo()!=null||u.getQuery()!=null||u.getFragment()!=null||u.getPort()<1||u.getPort()>65535||!(u.getPath().isEmpty()||u.getPath().equals("/")))throw new Exception("Invalid address");
        String[] parts=host.split("\\."); if(parts.length!=4)throw new Exception("IPv4 required"); int[] n=new int[4];
        for(int i=0;i<4;i++){if(!parts[i].matches("[0-9]{1,3}")||(parts[i].length()>1&&parts[i].startsWith("0")))throw new Exception("Invalid IPv4");n[i]=Integer.parseInt(parts[i]);if(n[i]>255)throw new Exception("Invalid IPv4");}
        if(!(n[0]==10||(n[0]==172&&n[1]>=16&&n[1]<=31)||(n[0]==192&&n[1]==168)))throw new Exception("Private Wi-Fi address required");
        return new URI("http",null,host,u.getPort(),"/",null,null);
    }
}
