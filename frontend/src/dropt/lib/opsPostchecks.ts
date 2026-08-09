import type { Locale } from "@dropt/i18n/messages";

function dash(v: string): string {
  return (v || "").trim() || "—";
}

/** Hostname change — success checklist (locale-aware). */
export function buildHostnameSuccessChecklist(
  locale: Locale,
  oldFqdn: string,
  newFqdn: string,
  ip: string,
): string[] {
  const old = dash(oldFqdn);
  const neu = dash(newFqdn);
  const addr = dash(ip);
  if (locale === "en") {
    return [
      "The requester must open a ticket to update DNS records using the format below.\n\n" +
        "Request path: DNS Definition / Change DNS Record\n" +
        "Sample request:\n" +
        `"${old} ${addr}" record should be updated so that it becomes "${neu} ${addr}".`,
      "Relevant teams must be informed so monitoring and Datastore entries can be updated.\n\n" +
        "Sample mail:\n" +
        "To: Sanallaştırma ve Bulut Platformları Yönetimi, Sistem İzleme ve Hizmet Analiz İşletimi, " +
        "Sistem İşletim ve İzleme, Altyapı İzleme\n" +
        "CC: Unix Linux Sistem Tasarım ve Planlama\n\n" +
        `Hostname of server "${old}" has been updated to "${neu}".\n` +
        "Please update the required Datastore and monitoring records.",
    ];
  }
  return [
    "Talep sahibinin belirtilen formatı kullanarak dns bilgilerinin güncellenmesi " +
      "için talep oluşturması gerekmektedir.\n\n" +
      "Talep Kırılım: DNS Tanımı / DNS Kayıt Değiştirme\n" +
      "Örnek Talep:\n" +
      `"${old} ${addr}" kaydının "${neu} ${addr}" olacak şekilde DNS kaydının ` +
      "güncellenmesini rica ederiz.",
    "İzleme ve Datastore alanlarının güncellenmesi üzere ilgili ekipler bilgilendirilmelidir.\n\n" +
      "Örnek Mail:\n" +
      "To: Sanallaştırma ve Bulut Platformları Yönetimi, Sistem İzleme ve Hizmet Analiz İşletimi, " +
      "Sistem İşletim ve İzleme, Altyapı İzleme\n" +
      "CC: Unix Linux Sistem Tasarım ve Planlama\n\n" +
      `"${old}" isimli sunucunun hostname bilgisi "${neu}" olarak güncellenmiştir.\n` +
      "Gerekli Datastore ve izleme kayıtları düzenlemesinin yapılmasını rica ederiz.",
  ];
}

/** IP change — success checklist (locale-aware). */
export function buildIpChangeSuccessChecklist(
  locale: Locale,
  fqdn: string,
  oldIp: string,
  newIp: string,
  isPrimary: boolean,
): string[] {
  const host = dash(fqdn).replace(/\.$/, "");
  const old = dash(oldIp);
  const neu = dash(newIp);
  if (locale === "en") {
    const dnsGate =
      "This step must be applied if the interface being changed has the primary IP address " +
      "(the IP that matches the DNS query). If it is a secondary IP address, this step is " +
      "not required.\n\n";
    const item1 = isPrimary
      ? dnsGate +
        "The requester must open a ticket to update DNS records using the format below.\n\n" +
        "Request path: DNS Definition / Change DNS Record\n" +
        "Sample request:\n" +
        `"${host} ${old}" record should be updated so that it becomes "${host} ${neu}".`
      : dnsGate +
        "Because this change was made on a secondary IP, a DNS record request is not required " +
        "(see the primary IP rule above).\n\n" +
        "Request path: DNS Definition / Change DNS Record\n" +
        "Sample request (primary IP only):\n" +
        `"${host} ${old}" record should be updated so that it becomes "${host} ${neu}".`;
    return [
      item1,
      "Relevant teams must be informed so monitoring definitions can be updated.\n\n" +
        "Sample mail:\n" +
        "To: Sistem İzleme ve Hizmet Analiz İşletimi, Sistem İşletim ve İzleme, Altyapı İzleme\n" +
        "CC: Unix Linux Sistem Tasarım ve Planlama\n\n" +
        `An IP change was performed on server "${host}" ("${old}"). ` +
        `"${host}" ==> "${neu}" has been updated.\n` +
        "Please update the required monitoring records.",
    ];
  }
  const dnsGate =
    "İşlem yapılan Interface birincil IP adresi ise (dns sorgusu ile eşleşen IP) " +
    "bu adımı uygulanmalıdır. Eğer ikincil IP adresi ise bu işlemin yapılması " +
    "gerek bulunmamaktadır.\n\n";
  const item1 = isPrimary
    ? dnsGate +
      "Talep sahibinin belirtilen formatı kullanarak dns bilgilerinin güncellenmesi " +
      "için talep oluşturması gerekmektedir.\n\n" +
      "Talep Kırılım: DNS Tanımı / DNS Kayıt Değiştirme\n" +
      "Örnek Talep:\n" +
      `"${host} ${old}" kaydının "${host} ${neu}" olacak şekilde DNS kaydının ` +
      "güncellenmesini rica ederiz."
    : dnsGate +
      "Bu işlem ikincil IP üzerinde yapıldığı için DNS kayıt talebi gerekmez " +
      "(yukarıdaki birincil IP kuralı).\n\n" +
      "Talep Kırılım: DNS Tanımı / DNS Kayıt Değiştirme\n" +
      "Örnek Talep (yalnızca birincil IP için):\n" +
      `"${host} ${old}" kaydının "${host} ${neu}" olacak şekilde DNS kaydının ` +
      "güncellenmesini rica ederiz.";
  return [
    item1,
    "İzleme tanımlarının güncellenmesi üzere ilgili ekipler bilgilendirilmelidir.\n\n" +
      "Örnek Mail:\n" +
      "To: Sistem İzleme ve Hizmet Analiz İşletimi, Sistem İşletim ve İzleme, Altyapı İzleme\n" +
      "CC: Unix Linux Sistem Tasarım ve Planlama\n\n" +
      `"${host}" ("${old}") isimli sunucuda ip değişikliği yapılmıştır. ` +
      `"${host}" ==> "${neu}" olarak güncellenmiştir.\n` +
      "Gerekli izleme kayıtları düzenlemesinin yapılmasını rica ederiz.",
  ];
}
