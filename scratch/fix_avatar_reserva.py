with open("C:/Users/willem/Documents/GitHub/fut-bin/montar_video.py", "r", encoding="utf-8") as f:
    mv = f.read()

target = """            if nome in visiveis:
                avatar = obter_avatar_jogador(nome, time_obj, tamanho=(av_sz, av_sz), cor_time=cor, pos=pos)
                if avatar:
                    img.paste(avatar, (x0 + 22, yy + (row_h - av_sz) // 2), avatar)
                nome_x = x0 + 22 + av_sz + 12"""

replacement = """            if nome in visiveis:
                av_item_sz = min(av_sz, 32) if eh_res else av_sz
                avatar = obter_avatar_jogador(nome, time_obj, tamanho=(av_item_sz, av_item_sz), cor_time=cor, pos=pos)
                if avatar:
                    img.paste(avatar, (x0 + 22, yy + (row_h - av_item_sz) // 2), avatar)
                nome_x = x0 + 22 + av_item_sz + 12"""

if target in mv:
    mv = mv.replace(target, replacement)
    with open("C:/Users/willem/Documents/GitHub/fut-bin/montar_video.py", "w", encoding="utf-8") as f:
        f.write(mv)
    print("Updated avatar size for reserves in montar_video.py")
else:
    print("Target not found in montar_video.py")
