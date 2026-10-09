package cn.infra.researcher.companion;
public final class AddressPolicyCheck {
    public static void main(String[] args) throws Exception {
        for(String value:new String[]{"http://192.168.1.5:54321/","10.0.0.8:80","http://172.31.0.2:65535/"})AddressPolicy.parse(value);
        for(String value:new String[]{"https://192.168.1.5:80/","http://example.com:80/","http://127.0.0.1:80/","http://8.8.8.8:80/","http://192.168.1.5:80/path","http://user:pass@192.168.1.5:80/","http://192.168.1.5:80/?key=x","http://192.168.999.1:80/","http://192.168.1.5/","http://172.32.0.1:80/"}){boolean rejected=false;try{AddressPolicy.parse(value);}catch(Exception e){rejected=true;}if(!rejected)throw new AssertionError(value);}
        System.out.println("Private LAN address validation passed.");
    }
}
