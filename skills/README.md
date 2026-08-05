# Cómo agregar una skill

Una skill es un archivo `.md` en esta carpeta con frontmatter YAML y un
cuerpo de instrucciones. Cuando el mensaje del usuario matchea el `name`,
`description` o alguna `keyword`, el cuerpo se inyecta en el system prompt
del agente para ese turno.

```markdown
---
name: nombre_corto_de_la_skill
description: Qué hace esta skill, en una oración.
keywords: [palabra1, palabra2, sinonimo]
---
Instrucciones concretas de cómo responder cuando esta skill aplica.
```

No hace falta reiniciar la app: hay un botón "Recargar skills" en la
sidebar.
