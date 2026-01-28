# Importare il progetto su GitHub

Questi passaggi servono a pubblicare il repository locale su GitHub mantenendo tutta la storia dei commit.

## 1) Crea un nuovo repository su GitHub

1. Vai su GitHub e crea un nuovo repository (vuoto, senza README/License per evitare conflitti).
2. Copia l’URL del repository (HTTPS o SSH), ad esempio:
   - HTTPS: `https://github.com/<utente>/<repo>.git`
   - SSH: `git@github.com:<utente>/<repo>.git`

## 2) Collega il repository remoto

Da terminale, nella root del progetto:

```bash
git remote add origin <URL>
```

Se `origin` esiste già e vuoi aggiornare l’URL:

```bash
git remote set-url origin <URL>
```

## 3) Pubblica il branch corrente

Se il branch locale si chiama `main`:

```bash
git push -u origin main
```

Se invece è `master`:

```bash
git push -u origin master
```

Se stai usando un altro branch (es. `work`):

```bash
git push -u origin work
```

## 4) Verifica su GitHub

Apri il repository su GitHub e verifica che i file siano visibili.

---

### Nota su credenziali

- **HTTPS**: potrebbe chiedere token personale (PAT) al posto della password.
- **SSH**: assicurati di avere le chiavi SSH configurate su GitHub.
