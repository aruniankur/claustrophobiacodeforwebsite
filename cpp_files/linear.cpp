#include <iostream>
#include <vector>
#include <cmath>
#include <algorithm>

using namespace std;

/* ================= BASIC LINEAR ALGEBRA ================= */

vector<double> matvec(const vector<vector<double>>& A,
                      const vector<double>& x) {
    vector<double> y(A.size(),0.0);
    for(int i=0;i<A.size();i++)
        for(int j=0;j<x.size();j++)
            y[i]+=A[i][j]*x[j];
    return y;
}

vector<double> residual(const vector<vector<double>>& A,
                        const vector<double>& x,
                        const vector<double>& b) {
    auto Ax = matvec(A,x);
    vector<double> r(b.size());
    for(int i=0;i<b.size();i++) r[i] = b[i] - Ax[i];
    return r;
}

/* ================= SOLVE LINEAR SYSTEM ================= */

vector<double> solve(vector<vector<double>> A,
                     vector<double> b) {
    int n = b.size();
    for(int i=0;i<n;i++) {
        int piv=i;
        for(int r=i;r<n;r++)
            if(fabs(A[r][i]) > fabs(A[piv][i])) piv=r;
        swap(A[i],A[piv]);
        swap(b[i],b[piv]);

        double d=A[i][i];
        for(int j=i;j<n;j++) A[i][j]/=d;
        b[i]/=d;

        for(int r=0;r<n;r++) if(r!=i) {
            double f=A[r][i];
            for(int j=i;j<n;j++) A[r][j]-=f*A[i][j];
            b[r]-=f*b[i];
        }
    }
    return b;
}

/* ================= NNLS ================= */

vector<double> nnls(const vector<vector<double>>& A,
                    const vector<double>& b) {

    int m=A.size(), n=A[0].size();
    vector<double> x(n,0.0);
    vector<int> P,Z;

    for(int i=0;i<n;i++) Z.push_back(i);

    while(true) {
        auto r = residual(A,x,b);

        int t=-1;
        double best=0;
        for(int j:Z){
            double c=0;
            for(int i=0;i<m;i++) c+=A[i][j]*r[i];
            if(c>best){best=c;t=j;}
        }

        if(t<0) break;

        P.push_back(t);
        Z.erase(find(Z.begin(),Z.end(),t));

        while(true) {
            int k=P.size();
            vector<vector<double>> ATA(k,vector<double>(k,0));
            vector<double> ATb(k,0);

            for(int i=0;i<k;i++)
                for(int j=0;j<k;j++)
                    for(int t=0;t<m;t++)
                        ATA[i][j]+=A[t][P[i]]*A[t][P[j]];

            for(int i=0;i<k;i++)
                for(int t=0;t<m;t++)
                    ATb[i]+=A[t][P[i]]*b[t];

            auto sol=solve(ATA,ATb);

            vector<double> z(n,0);
            for(int i=0;i<k;i++) z[P[i]]=sol[i];

            bool ok=true;
            for(int j:P) if(z[j]<=0) ok=false;
            if(ok){x=z;break;}

            double alpha=1e30;
            for(int j:P)
                if(z[j]<=0)
                    alpha=min(alpha,x[j]/(x[j]-z[j]));

            for(int i=0;i<n;i++)
                x[i]+=alpha*(z[i]-x[i]);

            for(auto it=P.begin();it!=P.end();){
                if(x[*it]<1e-12){
                    Z.push_back(*it);
                    it=P.erase(it);
                } else it++;
            }
        }
    }
    return x;
}

/* ================= BIAS ================= */

double compute_bias(const vector<vector<double>>& Phi,
                    const vector<double>& w,
                    const vector<double>& y) {
    double s=0;
    for(int i=0;i<y.size();i++){
        double p=0;
        for(int j=0;j<w.size();j++)
            p+=Phi[i][j]*w[j];
        s+=(y[i]-p);
    }
    return s/y.size();
}

/* ================= EXAMPLE ================= */

int main() {

    vector<vector<double>> X = {
        {1,2,3},
        {2,1,0},
        {3,1,2},
        {4,2,1},
        {5,3,2}
    };

    vector<double> y = {10,7,14,20,28};

    int B=X.size();

    vector<vector<double>> Phi(B,vector<double>(6));

    for(int i=0;i<B;i++){
        double x1=X[i][0],x2=X[i][1],x3=X[i][2];
        Phi[i]={x1,x2,x3,x1*x2,x2*x3,x3*x1};
    }

    auto w=nnls(Phi,y);
    double b=compute_bias(Phi,w,y);

    cout<<"w = ";
    for(double v:w) cout<<v<<" ";
    cout<<"\nb = "<<b<<"\n";
}
