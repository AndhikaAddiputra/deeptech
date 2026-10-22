# SAVENT

SAVENT memantau kualitas udara di kelas, lantai pabrik, dan kabin MLQ/CLQ di rig. Rekomendasi dihitung di perangkat, tanpa awan. Ambang kelas dan kabin awak 1000 ppm. Ambang lantai pabrik 2500 ppm, di bawah pajanan kerja 8 jam 5000 ppm.

Sidebar kiri memilih lingkungan. Mengganti halaman mengosongkan angka ruang sebelumnya.

Untuk hackathon, lingkungan kelas adalah digital twin: satu zona yang volumenya mengikuti luas lantai dan tinggi plafon. Aktuator perangkat keras belum dipasang. Tiga arah udara menggantikannya.

- **Masukkan udara luar** mengencerkan ruangan dengan udara luar.
- **Buang udara dalam** membuang udara kelas. Partikel udara pengganti dikurangi filter dummy. CO₂ tidak tersaring.
- **Biarkan diam** tidak menjalankan ventilasi mekanis. CO₂ naik karena penghuni.

Spesifikasi lengkap ada di [docs/FSD-SAVENT.md](docs/FSD-SAVENT.md). Rancangan sensor ada di [docs/HW-SENSING.md](docs/HW-SENSING.md).

## Menjalankan dasbor

Perlu Python 3.9 atau lebih baru. Tidak ada paket yang harus dipasang. Halaman memuat Three.js dari CDN, jadi browser perlu internet saat pertama kali dibuka.

```bash
python3 -m prototype.server
```

Buka [http://127.0.0.1:8765](http://127.0.0.1:8765). Satu detik di layar sama dengan 30 detik waktu sensor, supaya perubahan kelas terlihat dalam semenit pertama.

Jika port sudah dipakai:

```bash
PORT=8766 python3 -m prototype.server
```

Hentikan server dengan Ctrl+C.

## Bukti di layar

Banner di bawah ruang menulis tiga hal: prediksi lebih awal daripada aturan ambang lingkungan itu, lama CO₂ di atas ambang dibanding ruang yang dibiarkan diam, dan alasan kipas menyala atau diam. Node sensor dan kipas dinding ada di model 3D.

## Membaca dasbor

Tengah layar adalah kelas isometrik. Klik node sensor, grille udara masuk, atau grille udara keluar untuk melihat angkanya. Kartu di bawah melakukan hal yang sama. Kondisi udara luar hanya tertulis di panel kanan dan tidak digambar.

Panel kanan, dari atas:

| Kelompok | Fungsi |
|---|---|
| Keputusan | Status ventilasi, CO₂ terkoreksi, dan prediksi 10 menit |
| Udara luar | Angka luar yang menentukan udara boleh dimasukkan atau tidak |
| Siapa yang menggerakkan ventilasi | Seberapa jauh sistem boleh bertindak |
| Arah udara | Ikuti rekomendasi, atau kunci satu arah untuk percobaan |
| Ukuran kelas | Kelas kecil, kelas standar, atau auditorium |
| Uji gangguan | Suntikan kondisi. Bukan pengaturan gedung |

Dua pilihan penggerak:

- **Rekomendasi.** Sistem menyarankan arah udara. Kipas tidak bergerak. Ini mode bawaan.
- **Jalankan sendiri.** Kipas menyala sendiri: udara luar masuk, atau udara dalam dibuang bila udara luar lebih kotor.

## Uji

```bash
python3 -m unittest tests.test_fsd tests.test_twin
```

## Isi repo

| Path | Isi |
|---|---|
| `savent/logic.py` | Koreksi CO₂, bendera kualitas, prediksi, dan keputusan |
| `savent/twin.py` | Digital twin kelas dan tiga arah udara |
| `savent/model.py` | Koefisien regresi dan metrik terhadap tebakan persistensi |
| `prototype/` | Dasbor lokal |
| `firmware/savent_node/` | Sketsa ESP32. `SIMULATE 1` mengirim jejak lewat Serial tanpa sensor |
| `docs/` | Spesifikasi fungsional dan rancangan sensing |

Firmware memakai pin di `docs/HW-SENSING.md` dan pustaka PubSubClient. Isi `WIFI_SSID` di sketsa bila rekaman harus dikirim lewat MQTT.
