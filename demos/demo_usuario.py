"""
Demo do fluxo com usuário cadastrado: cadastro (ID) -> cronograma -> escolhas registradas -> estado salvo.

Suba os três mocks antes (porta 3001 DRI, 3002 TBCA, 3003 usuários):
    npx @mockoon/cli start --data mocks/dri.json mocks/tbca.json mocks/usuarios.json
Sem eles, tudo funciona com os arquivos locais (e o cadastro vai para usuarios_local.json).

    python demos/demo_usuario.py                    # cadastra uma pessoa nova
    python demos/demo_usuario.py --id exemplo       # usa o usuário de exemplo que já vem no mock
    python demos/demo_usuario.py --id <ID> --dias 5
"""
import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agents import cliente_kb                                         # noqa: E402
from agents.cliente_usuarios import ClienteUsuarios                   # noqa: E402
from agents.cronograma import Cronograma                              # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--id", help="ID de um usuário já cadastrado (sem isso, cadastra um novo)")
    p.add_argument("--dias", type=int, default=3)
    a = p.parse_args()

    cli = ClienteUsuarios()
    if a.id:
        usuario = cli.obter(a.id)
        print(f"Usuário {usuario['id']} ({usuario.get('nome', '')}) — {cli.fonte}")
    else:
        usuario = cli.criar("Pessoa da demo", {"sexo": "M", "idade": 42, "altura_cm": 178, "peso_kg": 82,
                                               "atividade": "pouco_ativo"},
                            regiao="Sudeste", restricoes=["sem_lactose"], nao_gosta=["jilo"])
        print(f"Cadastrado! ID: {usuario['id']} — {cli.fonte}")
    print(f"perfil: {usuario['dados_dri']} · região {usuario['regiao']} · restrições {usuario['restricoes']}")

    alimento = cliente_kb.alimento("C0209A")
    print(f"\nBase de conhecimento ({cliente_kb.buscar_alimentos(limite=1).attrs['fonte']}): "
          f"ex. {alimento['descricao'][:45]} = {alimento['energia_kcal']} kcal/100 g")

    rng = random.Random(0)
    for dia in range(1, a.dias + 1):
        c = Cronograma.do_usuario(usuario["id"], cli)      # todo dia recarrega perfil e estado do bandit
        if dia == 1:
            print(f"metas: {c.metas['fonte']} · despensa: {c.fonte_despensa}")
        print(f"\nDia {dia}")
        for refeicao in c.refeicoes:
            ops = c.opcoes(refeicao)
            pos = rng.randrange(len(ops["opcoes"]))      # aqui a pessoa escolheria; na demo é sorteado
            escolhida = ops["opcoes"][pos]
            c.escolher(refeicao, pos)
            print(f"  {ops['refeicao']:<14} escolheu a opção {pos + 1}: "
                  + " + ".join(f"{i['alimento'].split(',')[0]} {i['gramas']:.0f} g" for i in escolhida["itens"]))

    escolhas = cli.escolhas(usuario["id"])
    print(f"\n{len(escolhas)} escolhas registradas para {usuario['id']}; a última: {escolhas[-1]}")
    estado = cli.obter(usuario["id"])["estado_bandit"]
    print(f"estado do bandit salvo para: {', '.join(estado)}")
    print(f"\nPara continuar outro dia com o mesmo usuário:  python demos/demo_usuario.py --id {usuario['id']}")


if __name__ == "__main__":
    main()
